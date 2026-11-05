"""覆盖率计算：从任务记录汇总出「请求了什么 / 执行了什么 / 缺了什么」。

唯一实现，供报告接口、放行接口、批量矩阵共用。以前这段逻辑写在
`api/findings.py` 里，其他页面拿不到，只能各自发明口径。
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document import (
    STATUS_FAILED,
    TERMINAL_STATUSES,
    Document,
    DocumentRelease,
    DocumentTask,
    RELEASE_KIND_LABELS,
)
from app.schemas.coverage import CoverageOut, ReleaseOut, SkippedCheck

CHECK_LABELS = {
    "format": "格式规范",
    "typo": "错别字",
    "clause": "条款完整性",
    "cross": "数值勾稽",
}

# 这两个 skip 标记代表「整类检查没做」，而不是某一条规则跳过
WHOLE_CHECK_MARKERS = ("clause.check", "cross_rules")


def _skip_checker(rule: str) -> str:
    """把 skipped 里的规则 id 归到检查器：clause.check / cross_rules / format.* → 粗类。"""
    head = (rule or "").strip().lower().split(".")[0]
    if head.startswith("cross"):
        return "cross"
    return head if head in CHECK_LABELS else "other"


def _latest_task(db: Session, doc_id: uuid.UUID, task_type: str) -> DocumentTask | None:
    return db.execute(
        select(DocumentTask)
        .where(DocumentTask.document_id == doc_id, DocumentTask.task_type == task_type)
        .order_by(DocumentTask.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def latest_release(db: Session, doc_id: uuid.UUID) -> DocumentRelease | None:
    return db.execute(
        select(DocumentRelease)
        .where(DocumentRelease.document_id == doc_id)
        .order_by(DocumentRelease.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def release_out(row: DocumentRelease | None) -> ReleaseOut | None:
    if row is None:
        return None
    return ReleaseOut(
        id=str(row.id),
        kind=row.kind,
        label=RELEASE_KIND_LABELS.get(row.kind, row.kind),
        baseline_document_id=str(row.baseline_document_id) if row.baseline_document_id else None,
        changed_ratio=row.changed_ratio,
        note=row.note,
        created_at=row.created_at.isoformat() if row.created_at else None,
    )


def build_coverage(db: Session, doc: Document) -> CoverageOut:
    cov = CoverageOut()

    parse_task = _latest_task(db, doc.id, "parse")
    if parse_task is not None:
        warnings = parse_task.warnings or []
        cov.continued_with_warning = any(
            isinstance(w, dict) and w.get("code") == "user_continued_with_warning"
            for w in warnings
        )

    review_task = _latest_task(db, doc.id, "review")
    if review_task is None:
        # 解析完成但审查还没入队：不能当成「0 问题」，前端据此继续等
        cov.review_pending = True
        cov.complete = False
        cov.released = release_out(latest_release(db, doc.id))
        return cov

    if review_task.status not in TERMINAL_STATUSES:
        cov.review_pending = True
    if review_task.status == STATUS_FAILED:
        cov.review_failed = True

    stats = review_task.stats or {}
    cov.checks_requested = list(stats.get("checks") or [])
    cov.checker_warning_detail = list(stats.get("checker_warnings") or [])
    cov.checker_degraded = bool(cov.checker_warning_detail)
    cov.suppressed_rules = list(stats.get("suppressed") or [])

    grouped: dict[str, list[str]] = {}
    for rule in stats.get("skipped") or []:
        grouped.setdefault(_skip_checker(rule), []).append(rule)
    for checker, rules in grouped.items():
        cov.checks_skipped.append(SkippedCheck(
            checker=checker,
            label=CHECK_LABELS.get(checker, "其他规则"),
            rules=rules,
            whole_check=any(r in WHOLE_CHECK_MARKERS for r in rules),
        ))
    cov.checks_skipped.sort(key=lambda x: x.checker)

    whole = {s.checker for s in cov.checks_skipped if s.whole_check}
    cov.checks_executed = [c for c in cov.checks_requested if c not in whole]

    cov.complete = (
        not cov.review_pending
        and not cov.review_failed
        and not cov.checker_degraded
        and not any(s.whole_check for s in cov.checks_skipped)
    )
    cov.released = release_out(latest_release(db, doc.id))
    return cov
