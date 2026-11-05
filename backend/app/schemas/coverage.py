"""审查覆盖率（Coverage）：一等公民的数据结构。

为什么需要它：以前「哪些检查真的跑了」只散落在 review 任务 stats 的
`skipped` / `checker_warnings` 字段里，前端各页自己猜，结果「没检查」和
「检查了没问题」在界面上长得一模一样。现在统一成一个显式结构，
接口、报告页、批量矩阵都读同一份数据。
"""

from pydantic import BaseModel, Field


class SkippedCheck(BaseModel):
    checker: str
    label: str
    rules: list[str] = []
    whole_check: bool = False


class ReleaseOut(BaseModel):
    id: str
    kind: str
    label: str
    baseline_document_id: str | None = None
    changed_ratio: float | None = None
    note: str | None = None
    created_at: str | None = None


class CoverageOut(BaseModel):
    """一份审查到底覆盖了哪些检查——缺什么必须看得见。"""

    checks_requested: list[str] = []
    checks_executed: list[str] = []
    checks_skipped: list[SkippedCheck] = []
    suppressed_rules: list[str] = Field(
        default=[], description="被「规则停用」抑制的规则 id（不是没查出，是被关掉了）"
    )
    checker_degraded: bool = False
    checker_warning_detail: list[str] = []
    review_pending: bool = False
    review_failed: bool = False
    continued_with_warning: bool = False
    complete: bool = Field(
        default=True,
        description="True 表示请求的检查全部执行且无降级，报告可作为完整结论",
    )
    released: ReleaseOut | None = None
