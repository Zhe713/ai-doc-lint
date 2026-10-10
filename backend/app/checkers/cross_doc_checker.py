"""跨文档交叉比对检查器（W5 Day24）。

对比对组内多份文档（主合同 + 补充协议 / 招标 + 中标 + 合同）做两两勾稽，
findings 带 related_document_id 指明对端文档。全部确定性计算，0 token：

1. party_a_consistent   甲方主体在组内文档间不一致 → error
2. party_b_consistent   乙方主体在组内文档间不一致 → error
3. total_amount_consistent 总金额差异超 1% 容差 → warning（变更协议可能有意不同）
4. sign_date_sequence   后序文档签订日期早于首份文档 → warning

任一参与字段缺失即跳过该对（不误报）。
"""

import logging

from app.models.document import Document, DocumentField

log = logging.getLogger("cross_doc")

TOLERANCE_RATIO = 0.01


class CrossDocChecker:
    """组内文档两两勾稽；docs 按组内 position 升序传入。"""

    def __init__(self, collector, docs: list[Document],
                 fields_by_doc: dict[str, dict[str, DocumentField]]):
        self.collector = collector
        self.docs = docs
        self.fields_by_doc = fields_by_doc

    def run(self) -> None:
        n = len(self.docs)
        for i in range(n):
            for j in range(i + 1, n):
                self._compare_pair(self.docs[i], self.docs[j])

    # ---------------- 单对比对 ----------------

    def _compare_pair(self, doc_a: Document, doc_b: Document) -> None:
        fa = self.fields_by_doc[str(doc_a.id)]
        fb = self.fields_by_doc[str(doc_b.id)]
        self._check_party(doc_a, doc_b, fa, fb, "party_a", "甲方")
        self._check_party(doc_a, doc_b, fa, fb, "party_b", "乙方")
        self._check_amount(doc_a, doc_b, fa, fb)
        self._check_sign_sequence(doc_a, doc_b, fa, fb)

    def _emit(self, doc: Document, other: Document, *, rule_id: str,
              severity: str, message: str, suggestion: str | None) -> None:
        self.collector.add(
            checker="cross_doc",
            rule_id=rule_id,
            severity=severity,
            message=message,
            suggestion=suggestion,
            related_document_id=other.id,
            location=None,
        )

    # 当事人一致
    def _check_party(self, doc_a, doc_b, fa, fb, key: str, label: str) -> None:
        va = fa.get(key)
        vb = fb.get(key)
        if va is None or vb is None:
            return
        ta = (va.value_text or "").strip()
        tb = (vb.value_text or "").strip()
        if not ta or not tb:
            return
        if ta == tb:
            return
        self._emit(
            doc_a, doc_b,
            rule_id=f"{key}_consistent",
            severity="error",
            message=f"{label}不一致：本文件「{ta}」≠ 对端文件「{tb}」",
            suggestion="请核实组内文件是否属于同一交易主体",
        )

    # 总金额一致（1% 容差）
    def _check_amount(self, doc_a, doc_b, fa, fb) -> None:
        na = fa.get("total_amount")
        nb = fb.get("total_amount")
        if na is None or nb is None:
            return
        va = na.value_number
        vb = nb.value_number
        if va is None or vb is None or va <= 0 or vb <= 0:
            return
        if abs(va - vb) <= max(TOLERANCE_RATIO * max(va, vb), 0.01):
            return
        self._emit(
            doc_a, doc_b,
            rule_id="total_amount_consistent",
            severity="warning",
            message=(
                f"合同金额不一致：本文件 {va:,.2f} 元 ≠ 对端文件 {vb:,.2f} 元"
                f"（差异 {abs(va - vb):,.2f} 元）"
            ),
            suggestion="若为补充/变更协议请确认金额差异是否已在正文约定；否则需核实",
        )

    # 签订日期时序：后序文档不应早于首份文档
    def _check_sign_sequence(self, doc_a, doc_b, fa, fb) -> None:
        sa = fa.get("sign_date")
        sb = fb.get("sign_date")
        if sa is None or sb is None:
            return
        da = sa.value_date
        db = sb.value_date
        if da is None or db is None:
            return
        if db >= da:
            return
        self._emit(
            doc_b, doc_a,
            rule_id="sign_date_sequence",
            severity="warning",
            message=(
                f"后序文档签订日期 {db.date().isoformat()} 早于"
                f"首份文档 {da.date().isoformat()}，时序异常"
            ),
            suggestion="请核实后序文档是否为补充/变更协议及其签订时间",
        )
