"""review 流水线：按校验选项顺序执行检查器，findings 入表，汇总 stats，置 parsed。

Day11：骨架 + FindingCollector + 汇总；
Day12：format checker 接入；Day13：typo checker 接入；
Day14：检查器编排由意图漏斗 L1/L2 的路由结果（stats.checks）决定。
"""

import logging

from sqlalchemy.orm import Session

from app.models.document import (
    CHECKERS,
    STATUS_PARSED,
    CheckFinding,
    Document,
    DocumentTask,
)
from app.services import task_state
from app.tasks.events import append_event

log = logging.getLogger("review")


class FindingCollector:
    """检查器统一收集器：构造 finding 行并计入本任务，最后一次性 flush。"""

    def __init__(self, db: Session, task: DocumentTask):
        self.db = db
        self.task = task
        self.items: list[CheckFinding] = []
        self.skipped: list[str] = []

    def note_skipped(self, rule: str) -> None:
        """检查器对当前格式无法可靠执行的规则显式记 skip（不产生误报）。"""
        if rule not in self.skipped:
            self.skipped.append(rule)

    def add(
        self,
        *,
        checker: str,
        rule_id: str,
        message: str,
        severity: str = "warning",
        location: dict | None = None,
        suggestion: str | None = None,
    ) -> CheckFinding:
        finding = CheckFinding(
            document_id=self.task.document_id,
            task_id=self.task.id,
            user_id=self.task.user_id,
            checker=checker,
            rule_id=rule_id,
            severity=severity,
            location=location,
            message=message,
            suggestion=suggestion,
        )
        self.db.add(finding)
        self.items.append(finding)
        return finding

    def flush(self) -> None:
        self.db.flush()


def summarize(findings: list[CheckFinding], skipped: list[str] | None = None) -> dict:
    by_severity = {"error": 0, "warning": 0, "info": 0}
    by_checker: dict[str, int] = {}
    for f in findings:
        by_severity[f.severity] = by_severity.get(f.severity, 0) + 1
        by_checker[f.checker] = by_checker.get(f.checker, 0) + 1
    out = {
        "total": len(findings),
        "by_severity": by_severity,
        "by_checker": by_checker,
    }
    if skipped:
        out["skipped"] = list(skipped)
    return out


def run_review_pipeline(db: Session, task: DocumentTask, document: Document) -> None:
    options = task.stats or {}
    requested = options.get("checks") or list(CHECKERS)
    append_event(
        db, task, "stage_progress", stage="review",
        message=f"校验开始：{', '.join(requested)}",
    )
    db.commit()

    collector = FindingCollector(db, task)

    if "format" in requested:
        from app.checkers.format_checker import FormatChecker

        FormatChecker(db, document, collector, options).run()
    if "typo" in requested:
        # Day13 接入
        pass

    collector.flush()
    db.commit()

    stats = {**summarize(collector.items, collector.skipped), "checks": requested}
    task_state.change_status(
        db, task, STATUS_PARSED,
        event_type="task_succeeded", stage="done",
        message="校验完成",
        fields={"stats": stats},
    )
