"""W7 学习闭环管理接口：反馈统计、规则停用建议（人工闸门）、操作日志、手动触发调优。"""

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.db.session import get_db
from app.models.document import (
    FINDING_IGNORED,
    CheckFinding,
    LearningLog,
    LearningSuggestion,
    SUGGESTION_CONFIRMED,
    SUGGESTION_PENDING,
    SUGGESTION_REJECTED,
)
from app.models.user import User

router = APIRouter(prefix="/admin/learning", tags=["learning"])

# checker → 规则包类型映射（停用建议确认时匹配自定义规则包）
CHECKER_PACK_TYPE = {
    "format": "format",
    "clause": "clause",
    "field": "field",
    "cross": "cross",
}
# typo 误报词提取：message = 疑似错别字：「wrong」建议改为「right」
TYPO_WRONG_RE = re.compile(r"「(.+?)」建议改为")

# 停用建议阈值
SUGGEST_FALSE_RATE = 0.3
SUGGEST_MIN_FALSE = 3


class SuggestionDecision(BaseModel):
    action: str  # confirm / reject


# ---------------- 反馈统计看板 ----------------


@router.get("/feedback")
def learning_feedback(
    db: Session = Depends(get_db), _: User = Depends(require_admin)
) -> dict:
    """按 checker/rule 聚合：命中数、误报数、确认数、误报率、最近反馈时间。"""
    rows = db.execute(
        select(
            CheckFinding.checker,
            CheckFinding.rule_id,
            func.count(CheckFinding.id).label("hit_count"),
            func.count(CheckFinding.id).filter(
                CheckFinding.status == FINDING_IGNORED
            ).label("false_count"),
            func.count(CheckFinding.id).filter(
                CheckFinding.feedback_reason == "confirmed"
            ).label("confirmed_count"),
            func.max(CheckFinding.updated_at).label("last_feedback_at"),
        )
        .where(
            (CheckFinding.status == FINDING_IGNORED)
            | (CheckFinding.feedback_reason.is_not(None))
        )
        .group_by(CheckFinding.checker, CheckFinding.rule_id)
        .order_by(func.count(CheckFinding.id).desc())
    ).all()

    items = []
    for checker, rule_id, hit, false_cnt, confirmed_cnt, last_at in rows:
        rate = round(false_cnt / hit, 4) if hit else 0.0
        items.append({
            "checker": checker,
            "rule_id": rule_id,
            "hit_count": hit,
            "false_count": false_cnt,
            "confirmed_count": confirmed_cnt,
            "false_rate": rate,
            "last_feedback_at": last_at.isoformat() if last_at else None,
        })

    # W7-5 误报原因分布（结构化归因）：按 checker/rule/cause 计数
    cause_rows = db.execute(
        select(
            CheckFinding.checker,
            CheckFinding.rule_id,
            CheckFinding.feedback_cause,
            func.count(CheckFinding.id),
        )
        .where(
            CheckFinding.status == FINDING_IGNORED,
            CheckFinding.feedback_cause.is_not(None),
        )
        .group_by(CheckFinding.checker, CheckFinding.rule_id,
                  CheckFinding.feedback_cause)
    ).all()
    causes: dict[str, dict[str, dict[str, int]]] = {}
    for checker, rule_id, cause, cnt in cause_rows:
        causes.setdefault(checker, {}).setdefault(rule_id, {})[cause or "other"] = cnt
    for it in items:
        it["causes"] = causes.get(it["checker"], {}).get(it["rule_id"], {})
    return {"items": items}


# ---------------- 停用建议（人工闸门） ----------------


@router.get("/suggestions")
def list_suggestions(
    status: str = SUGGESTION_PENDING,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    rows = db.execute(
        select(LearningSuggestion)
        .where(LearningSuggestion.status == status)
        .order_by(LearningSuggestion.false_rate.desc(), LearningSuggestion.id.desc())
    ).scalars().all()
    return {"items": [
        {
            "id": s.id,
            "checker": s.checker,
            "rule_id": s.rule_id,
            "reason": s.reason,
            "hit_count": s.hit_count,
            "false_count": s.false_count,
            "false_rate": s.false_rate,
            "status": s.status,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "resolved_at": s.resolved_at.isoformat() if s.resolved_at else None,
        }
        for s in rows
    ]}


def _disable_rule(db: Session, suggestion: LearningSuggestion, admin: User) -> dict:
    """把「确认停用」落到规则级覆盖表——内置规则也能真停用。

    以前这里是「找包含该 rule_id 的自定义包并整包停用」：内置规则根本没有包可停，
    于是只写了一条日志，界面却显示"已停用"；即使命中自定义包，也会把整个包里
    其它正常规则一起关掉，代价过大。现在按 (pack_type, rule_id) 精确停用。
    """
    pack_type = CHECKER_PACK_TYPE.get(suggestion.checker) or suggestion.checker
    from app.checkers.loader import invalidate_pack_caches
    from app.services.rule_overrides import disable_rule

    row = disable_rule(
        db,
        pack_type=pack_type,
        rule_id=suggestion.rule_id,
        user_id=None,  # 管理员决策 = 全局生效
        reason=f"学习闭环确认停用（误报率 {suggestion.false_rate:.0%}）"
        if suggestion.false_rate is not None else "学习闭环确认停用",
        created_by=admin.id,
    )
    db.flush()
    return {
        "pack_type": pack_type,
        "rule_id": row.rule_id,
        "scope": "global",
        "disabled_rule_id": str(row.id),
    }


@router.post("/suggestions/{suggestion_id}/decision")
def decide_suggestion(
    suggestion_id: int,
    body: SuggestionDecision,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    s = db.get(LearningSuggestion, suggestion_id)
    if s is None:
        raise HTTPException(status_code=404, detail="建议不存在")
    if s.status != SUGGESTION_PENDING:
        raise HTTPException(status_code=409, detail="该建议已处理")

    now = datetime.now(timezone.utc)
    if body.action == "confirm":
        disabled = _disable_rule(db, s, admin)
        from app.checkers.loader import invalidate_pack_caches

        invalidate_pack_caches()
        s.status = SUGGESTION_CONFIRMED
        s.resolved_at = now
        db.add(LearningLog(
            action="suggestion_confirm",
            detail={
                "suggestion_id": s.id,
                "checker": s.checker,
                "rule_id": s.rule_id,
                **disabled,
                "by": str(admin.id),
            },
        ))
        # W8 审计：规则停用操作留痕
        from app.services.audit_service import write_audit

        write_audit(db, action="rule_decision", user_id=admin.id, username=admin.username,
                    target=s.rule_id,
                    detail={"decision": "confirm", "checker": s.checker,
                            "pack_type": disabled["pack_type"], "scope": "global"})
        db.commit()
        return {"ok": True, "disabled_rule": disabled}
    if body.action == "reject":
        s.status = SUGGESTION_REJECTED
        s.resolved_at = now
        db.add(LearningLog(
            action="suggestion_reject",
            detail={
                "suggestion_id": s.id,
                "checker": s.checker,
                "rule_id": s.rule_id,
                "by": str(admin.id),
            },
        ))
        # W8 审计：规则建议拒绝留痕
        from app.services.audit_service import write_audit

        write_audit(db, action="rule_decision", user_id=admin.id, username=admin.username,
                    target=s.rule_id, detail={"decision": "reject", "checker": s.checker})
        db.commit()
        return {"ok": True}
    raise HTTPException(status_code=422, detail="动作仅支持 confirm / reject")


# ---------------- 操作日志与手动触发 ----------------


@router.get("/logs")
def learning_logs(
    limit: int = 50,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    limit = min(max(limit, 1), 200)
    rows = db.execute(
        select(LearningLog)
        .order_by(LearningLog.id.desc())
        .limit(limit)
    ).scalars().all()
    return {"items": [
        {
            "id": r.id,
            "action": r.action,
            "detail": r.detail,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]}


@router.post("/run-tuning")
def run_tuning(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    """手动触发一次调优（立即执行，前台同步等结果）。"""
    from app.services.audit_service import write_audit
    from app.tasks.learning import run_daily_tuning

    try:
        summary = run_daily_tuning(trigger="manual", by=str(admin.id))
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=500, detail=f"调优执行失败：{type(exc).__name__}: {exc}")
    # W8 审计：学习诊断留痕
    write_audit(db, action="learning_tuning", user_id=admin.id, username=admin.username,
                detail={"whitelist_added": summary.get("whitelist_added", 0),
                        "whitelist_pending": summary.get("whitelist_pending", [])})
    db.commit()
    return summary
