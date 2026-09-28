"""L1 规则层：纯规则驱动（关键词/正则），毫秒级、0 token。

W3 Day14 仅实现 pipeline 域：
- 用户在上传区显式勾选（doc_type / checks）→ 直接命中；
- 文件名关键词/正则推断文档类型；
- 未覆盖的槽位（如未勾选检查项）交给 L2 确定性补全。
"""

import re

from app.router import RouteResult

INTENT_PIPELINE_REVIEW = "pipeline.review"

# 文档类型关键词（文件名命中即归类；顺序即优先级）
DOC_TYPE_KEYWORDS = [
    ("contract", ("合同", "协议", "契约", "合约")),
    ("tender", ("招标", "投标", "中标", "标书", "竞标")),
    ("policy", ("制度", "办法", "规定", "章程", "细则", "规范")),
    ("report", ("报告", "汇报", "总结", "纪要")),
]

KNOWN_CHECKS = ("format", "typo", "clause", "cross")


class RuleLayer:
    layer = "rule"

    def match_pipeline(self, filename: str, options: dict) -> RouteResult:
        explicit_type = (options.get("doc_type") or "auto").strip()
        checks = self._clean_checks(options.get("checks"))

        slots: dict = {}
        if checks:
            slots["checks"] = checks
        if explicit_type and explicit_type != "auto":
            slots["doc_type"] = explicit_type
        else:
            guess = self._guess_doc_type(filename)
            if guess:
                slots["doc_type"] = guess  # 规则命中，仍属 L1

        resolved = "checks" in slots and "doc_type" in slots
        return RouteResult(
            intent_code=INTENT_PIPELINE_REVIEW,
            layer=self.layer,
            confidence=0.99 if resolved else 0.8,
            slots=slots,
        )

    @staticmethod
    def _clean_checks(value) -> list[str]:
        if not value:
            return []
        if isinstance(value, (list, tuple)):
            raw = list(value)
        else:
            raw = re.split(r"[,，]", str(value))
        out = [c.strip() for c in raw if c.strip() in KNOWN_CHECKS]
        # 去重保序
        return list(dict.fromkeys(out))

    @staticmethod
    def _guess_doc_type(filename: str) -> str | None:
        name = filename or ""
        for doc_type, keywords in DOC_TYPE_KEYWORDS:
            if any(k in name for k in keywords):
                return doc_type
        return None
