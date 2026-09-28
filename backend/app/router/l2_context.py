"""L2 上下文层：确定性补槽，纯规则计算、不调 LLM。

W3 Day14 pipeline 域：
- doc_type 仍缺 → general（不猜具体类型，避免误导规则包）；
- checks 仍缺 → 系统默认检查项（format+typo）；
- 非法 checks 过滤；
- 用户默认偏好继承在 W6 接入（私有模板/默认检查项）。

assistant 域（W4）在此基础上增加对话状态机：槽位继承、省略/指代消解、缺槽反问。
"""

from app.router import RouteResult


class ContextLayer:
    layer = "context"

    def match_pipeline(self, partial_slots: dict, filename: str, *, default_checks=None) -> RouteResult:
        slots = dict(partial_slots)
        if not slots.get("doc_type"):
            slots["doc_type"] = "general"
        if not slots.get("checks"):
            slots["checks"] = list(default_checks or ["format", "typo"])
        return RouteResult(
            intent_code="pipeline.review",
            layer=self.layer,
            confidence=0.9,
            slots=slots,
        )
