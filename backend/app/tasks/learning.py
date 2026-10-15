"""W7 自学习调优任务：诊断反馈 → 白名单自动扩充（可回滚）→ 规则停用建议（人工闸门）。

- 每日由 Celery beat 触发（learn 队列）；系统管理页可手动同步触发。
- typo 误报词自动写入 rules/typo_whitelist_auto.txt（独立文件，可一键回滚）；
- 误报率超阈值的规则生成停用建议挂起，管理员在系统管理页确认后停用。
- 全部动作写 learning_logs 留痕。
"""

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select

from app.api.learning import (
    SUGGEST_FALSE_RATE,
    SUGGEST_MIN_FALSE,
    TYPO_WRONG_RE,
)
from app.db.session import SessionLocal
from app.models.document import (
    FINDING_IGNORED,
    FINDING_OPEN,
    FINDING_FIXED,
    CHECKER_TYPO,
    CheckFinding,
    LearningLog,
    LearningSuggestion,
    SUGGESTION_PENDING,
)
from app.tasks.celery_app import QUEUE_LEARN, celery_app

log = logging.getLogger("learning")

# 自动白名单文件（与内置 typo_whitelist.txt 并存，可一键回滚删除）
RULES_DIR = Path(__file__).parent.parent / "checkers" / "rules"
AUTO_WHITELIST = RULES_DIR / "typo_whitelist_auto.txt"

# W7-5 golden 集版本化：manifest 记录版本与 doc 清单，调优前对候选词做 golden 验证
GOLDEN_MANIFEST = Path("/app/corpus/acceptance_golden/golden_manifest.json")
GOLDEN_RESULTS = Path("/app/corpus/acceptance_golden/l1_results.json")


def _read_auto_words() -> set[str]:
    if not AUTO_WHITELIST.exists():
        return set()
    words = set()
    for line in AUTO_WHITELIST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            words.add(line)
    return words


def _append_auto_words(words: set[str]) -> tuple[int, int]:
    """追加新词到 auto 白名单，返回 (新增数, 总数)。"""
    existing = _read_auto_words()
    new_words = sorted(w for w in words if w and w not in existing)
    if not new_words:
        return 0, len(existing)
    with AUTO_WHITELIST.open("a", encoding="utf-8") as fh:
        if fh.tell() == 0:
            fh.write("# W7 自动扩充白名单（用户反馈误报自动加入，可整文件删除回滚）\n")
        for w in new_words:
            fh.write(w + "\n")
    return len(new_words), len(existing) + len(new_words)


def _typo_false_words(db) -> set[str]:
    """从 typo 误报反馈中提取原文词（「xxx」建议改为）。"""
    rows = db.execute(
        select(CheckFinding.message)
        .where(
            CheckFinding.checker == CHECKER_TYPO,
            CheckFinding.status == FINDING_IGNORED,
        )
    ).scalars().all()
    words = set()
    for msg in rows:
        m = TYPO_WRONG_RE.search(msg or "")
        if m:
            words.add(m.group(1).strip())
    return words


def _golden_doc_ids() -> tuple[set[str], str]:
    """读取 golden 集 doc 清单（manifest 优先，回退 l1_results.json）。

    返回 (doc_id 集合, 版本号)。文件缺失时返回空集与未知版本（跳过 golden 验证）。
    """
    manifest = GOLDEN_MANIFEST
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            return set(data.get("doc_ids", [])), str(data.get("version", "unknown"))
        except Exception as exc:  # noqa: BLE001
            log.warning("golden manifest 解析失败：%s", exc)
    results = GOLDEN_RESULTS
    if results.exists():
        try:
            rows = json.loads(results.read_text(encoding="utf-8"))
            ids = {r.get("doc_id") for r in rows if r.get("doc_id")}
            return ids, "legacy(no-manifest)"
        except Exception as exc:  # noqa: BLE001
            log.warning("golden l1_results 解析失败：%s", exc)
    return set(), "unavailable"


def _verify_candidate_words(db, words: set[str]) -> tuple[set[str], dict[str, str]]:
    """W7-5 白名单先验证再生效。

    候选词两级验证，任一失败则**不自动生效**（挂起人工，写日志）：
    1) 信号验证：DB 中同词 findings 存在 confirmed / fixed / open 状态
       （说明系统或用户认为该词确有问题）→ 不自动加入；
    2) golden 验证：该词出现在 golden 真实合同集的 typo findings 中
       （说明加入会掩盖 golden 真实问题）→ 不自动加入。
    返回 (安全词, {不安全词: 原因})。
    """
    if not words:
        return set(), {}
    safe, pending = set(), {}
    golden_ids, golden_ver = _golden_doc_ids()

    # 一次查出所有同词 findings（含状态与文档归属）
    rows = db.execute(
        select(CheckFinding.id, CheckFinding.status,
               CheckFinding.feedback_reason, CheckFinding.document_id,
               CheckFinding.message)
        .where(CheckFinding.checker == CHECKER_TYPO)
    ).all()
    for w in sorted(words):
        reasons = []
        # 1) 信号验证
        for _, status, fb_reason, _doc_id, msg in rows:
            if f"「{w}」" in (msg or ""):
                if status in (FINDING_OPEN, FINDING_FIXED) or fb_reason == "confirmed":
                    reasons.append(
                        "同词问题曾被确认或未处理（存在 open/fixed/confirmed 记录）"
                    )
                    break
        # 2) golden 验证（manifest 可用时）
        if not reasons and golden_ids:
            for _id, _st, _fb, doc_id, msg in rows:
                if str(doc_id) in golden_ids and f"「{w}」" in (msg or ""):
                    reasons.append(
                        f"该词在 golden 真实合同集（{golden_ver}）中被判定为问题，自动加入会掩盖真实问题"
                    )
                    break
        if reasons:
            pending[w] = "；".join(reasons)
        else:
            safe.add(w)
    return safe, pending


def _run_tuning(db, trigger: str, by: str | None) -> dict:
    now = datetime.now(timezone.utc)

    # 1) typo 误报 → 白名单验证 → 安全词自动扩充，不安全词挂起人工
    false_words = _typo_false_words(db)
    safe_words, pending_map = _verify_candidate_words(db, false_words)
    added, total = _append_auto_words(safe_words)
    if added:
        db.add(LearningLog(
            action="whitelist_add",
            detail={
                "trigger": trigger,
                "words": sorted(safe_words),
                "added": added,
                "total": total,
                "file": "typo_whitelist_auto.txt",
                "rollback": "删除该文件即可回滚",
                "verified": True,
            },
        ))
    if pending_map:
        db.add(LearningLog(
            action="whitelist_skipped",
            detail={
                "trigger": trigger,
                "words": sorted(pending_map),
                "reasons": pending_map,
                "note": "未通过验证不自动生效，如需加入请手动编辑 typo_whitelist_auto.txt",
            },
        ))

    # 2) 全部规则误报率诊断 → 停用建议（同规则未决建议去重）
    stats = db.execute(
        select(
            CheckFinding.checker,
            CheckFinding.rule_id,
            func.count(CheckFinding.id),
            func.count(CheckFinding.id).filter(
                CheckFinding.status == FINDING_IGNORED
            ),
        )
        .group_by(CheckFinding.checker, CheckFinding.rule_id)
    ).all()

    pending_keys = set(
        tuple(r) for r in db.execute(
            select(LearningSuggestion.checker, LearningSuggestion.rule_id)
            .where(LearningSuggestion.status == SUGGESTION_PENDING)
        ).all()
    )
    suggestions = []
    for checker, rule_id, hit, false_cnt in stats:
        if hit < SUGGEST_MIN_FALSE:
            continue
        rate = false_cnt / hit
        if rate >= SUGGEST_FALSE_RATE and (checker, rule_id) not in pending_keys:
            db.add(LearningSuggestion(
                checker=checker,
                rule_id=rule_id,
                reason=(
                    f"误报率 {rate:.1%}（{false_cnt}/{hit}）超过阈值 "
                    f"{SUGGEST_FALSE_RATE:.0%}，建议停用或调整规则"
                ),
                hit_count=hit,
                false_count=false_cnt,
                false_rate=round(rate, 4),
                status=SUGGESTION_PENDING,
            ))
            pending_keys.add((checker, rule_id))
            suggestions.append(rule_id)

    if suggestions:
        db.add(LearningLog(
            action="rule_suggest",
            detail={
                "trigger": trigger,
                "rules": suggestions,
                "threshold_rate": SUGGEST_FALSE_RATE,
                "note": "需管理员在系统管理-学习反馈中确认后停用",
            },
        ))

    db.add(LearningLog(
        action="tuning_run",
        detail={
            "trigger": trigger,
            "whitelist_added": added,
            "whitelist_total": total,
            "whitelist_pending": sorted(pending_map) or None,
            "suggested_rules": suggestions,
            "by": by,
        },
    ))
    db.commit()
    return {
        "ok": True,
        "trigger": trigger,
        "whitelist_added": added,
        "whitelist_total": total,
        "whitelist_pending": sorted(pending_map),
        "suggested_rules": suggestions,
        "at": now.isoformat(),
    }


@celery_app.task(name="app.tasks.learning.run_daily_tuning", bind=True, max_retries=2)
def run_daily_tuning(self, trigger: str = "daily", by: str | None = None) -> dict:
    db = SessionLocal()
    try:
        return _run_tuning(db, trigger, by)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log.exception("learning tuning failed: %s", exc)
        raise self.retry(exc=exc, countdown=30)
    finally:
        db.close()


def enqueue_daily_tuning() -> None:
    run_daily_tuning.apply_async(args=["daily"], queue=QUEUE_LEARN)
