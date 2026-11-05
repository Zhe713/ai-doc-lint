"""review 流水线：按校验选项顺序执行检查器，findings 入表，汇总 stats，置 parsed。

Day11：骨架 + FindingCollector + 汇总；
Day12：format checker 接入；Day13：typo checker 接入；
Day14：检查器编排由意图漏斗 L1/L2 的路由结果（stats.checks）决定。
"""

import logging

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import (
    STATUS_PARSED,
    CheckFinding,
    Document,
    DocumentTask,
)
from app.services import task_state
from app.tasks.events import append_event

log = logging.getLogger("review")


class FindingCollector:
    """检查器统一收集器：构造 finding 行并计入本任务，最后一次性 flush。

    `disabled` 是「单条规则停用」的 (pack_type, rule_id) 集合。放在收集器这一层
    做兜底过滤，是为了覆盖所有检查器——包括 format/typo 这类不走规则包列表、
    无法在 loader 层过滤的规则。被抑制的条目记进 `suppressed`，让「规则被停用」
    在统计里看得见，而不是悄悄消失。
    """

    def __init__(self, db: Session, task: DocumentTask,
                 disabled: set[tuple[str, str]] | None = None):
        self.db = db
        self.task = task
        self.items: list[CheckFinding] = []
        self.skipped: list[str] = []
        self.warnings: list[str] = []
        self.disabled = disabled or set()
        self.suppressed: list[str] = []

    def add_warning(self, message: str) -> None:
        """检查器自身的运行告警（降级/能力受限等），区别于文档问题 finding。"""
        if message not in self.warnings:
            self.warnings.append(message)

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
        related_document_id=None,
        source: str = "rule",
        llm_reason: str | None = None,
        llm_model: str | None = None,
    ) -> CheckFinding | None:
        pack_type = "cross" if checker == "cross_doc" else checker
        if (pack_type, rule_id) in self.disabled:
            if rule_id not in self.suppressed:
                self.suppressed.append(rule_id)
            return None
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
            related_document_id=related_document_id,
            source=source,
            llm_reason=llm_reason,
            llm_model=llm_model,
        )
        self.db.add(finding)
        self.items.append(finding)
        return finding

    def flush(self) -> None:
        self.db.flush()


def summarize(
    findings: list[CheckFinding],
    skipped: list[str] | None = None,
    warnings: list[str] | None = None,
    suppressed: list[str] | None = None,
) -> dict:
    by_severity = {"error": 0, "warning": 0, "info": 0}
    by_checker: dict[str, int] = {}
    by_source: dict[str, int] = {"rule": 0, "hybrid": 0, "llm": 0}
    for f in findings:
        by_severity[f.severity] = by_severity.get(f.severity, 0) + 1
        by_checker[f.checker] = by_checker.get(f.checker, 0) + 1
        src = getattr(f, "source", None) or "rule"
        by_source[src] = by_source.get(src, 0) + 1
    out = {
        "total": len(findings),
        "by_severity": by_severity,
        "by_checker": by_checker,
        "by_source": by_source,
    }
    if skipped:
        out["skipped"] = list(skipped)
    if warnings:
        out["checker_warnings"] = list(warnings)
    if suppressed:
        out["suppressed"] = list(suppressed)
    return out


def _disabled_rules(db: Session, user_id) -> set[tuple[str, str]]:
    """该用户生效的规则停用集合；查询失败时返回空集（不能让审查整体失败）。"""
    try:
        from app.services.rule_overrides import disabled_rule_set

        return disabled_rule_set(db, user_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("读取规则停用覆盖失败，按全部启用处理: %s", type(exc).__name__)
        return set()


def run_review_pipeline(db: Session, task: DocumentTask, document: Document) -> None:
    options = task.stats or {}
    requested = options.get("checks") or list(settings.default_checks)
    append_event(
        db, task, "stage_progress", stage="review",
        message=f"校验开始：{', '.join(requested)}",
    )
    db.commit()

    collector = FindingCollector(db, task, _disabled_rules(db, task.user_id))

    # 字段抽取：规则层始终执行（0 token）；仅当请求交叉比对时允许 LLM 补抽
    from app.extract.field_extractor import FieldExtractor

    extractor = FieldExtractor(db, document,
                               allow_llm="cross" in requested)
    extractor.run()
    for warning in extractor.warnings:
        collector.add_warning(warning)

    if "format" in requested:
        from app.checkers.format_checker import FormatChecker

        FormatChecker(db, document, collector, options).run()
    if "typo" in requested:
        from app.checkers.typo_checker import TypoChecker

        TypoChecker(db, document, collector, options).run()
    if "clause" in requested:
        from app.checkers.clause_checker import ClauseChecker

        ClauseChecker(db, document, collector, options).run()
    if "cross" in requested:
        from app.checkers.cross_checker import CrossChecker

        CrossChecker(db, document, collector, options).run()

    collector.flush()
    db.commit()

    stats = {
        **summarize(collector.items, collector.skipped, collector.warnings,
                    collector.suppressed),
        "checks": requested,
    }
    task_state.change_status(
        db, task, STATUS_PARSED,
        event_type="task_succeeded", stage="done",
        message="校验完成",
        fields={"stats": stats},
    )
