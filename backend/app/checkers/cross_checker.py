"""文档内交叉比对（勾稽）检查器（W5 Day23）。

基于 document_fields 抽取出的结构化字段做确定性一致性校验，0 token：
1. 金额大写 = 小写金额（中文大写转数字后比较）；
2. 单价 × 数量 = 总价（1% 容差，容忍四舍五入差异）；
3. 签订日期 ≤ 交付日期；
4. 公告日期不早于签订日期（info 提示）。

参与勾稽的字段任一缺失时跳过该条规则（不误报）。
"""

import logging
import re
from datetime import datetime

from app.checkers.loader import load_cross_rules
from app.models.document import (
    CheckFinding,
    Document,
    DocumentField,
)

log = logging.getLogger("cross")

# ---- 中文大写金额转数字（零壹贰叁肆伍陆柒捌玖拾佰仟万亿） ----

_CN_NUM = {
    "零": 0, "壹": 1, "贰": 2, "叁": 3, "肆": 4,
    "伍": 5, "陆": 6, "柒": 7, "捌": 8, "玖": 9,
}
_CN_UNIT = {"拾": 10, "佰": 100, "仟": 1000, "万": 10000, "亿": 100000000}
_CN_TAIL = ("元整", "圆整", "元正", "圆正", "元", "圆", "整", "正")
_CN_CHARSET = "[零壹贰叁肆伍陆柒捌玖拾佰仟万亿元圆整正]+"


def chinese_upper_to_number(s: str) -> float | None:
    """中文大写金额转数字（元）；含角分或解析失败返回 None。

    例：'壹佰贰拾叁万肆仟伍佰陆拾柒元整' -> 1234567.0
        '人民币壹佰零捌万伍仟元整' -> 1085000.0
        '玖佰玖拾玖元玖角玖分' -> None（角分暂不支持）
    """
    if not s:
        return None
    s = s.strip()
    if "角" in s or "分" in s:
        return None
    m = re.search(_CN_CHARSET, s)
    if not m:
        return None
    s = m.group(0)
    for tail in _CN_TAIL:
        s = s.replace(tail, "")
    if not s:
        return None
    total = 0.0
    section = 0.0
    num = 0.0
    for ch in s:
        if ch in _CN_NUM:
            num = _CN_NUM[ch]
        elif ch in _CN_UNIT:
            unit = _CN_UNIT[ch]
            if unit in (10000, 100000000):
                section = (section + num) * unit
                total += section
                section = 0.0
                num = 0.0
            else:
                section += (num if num else 1.0) * unit
                num = 0.0
        else:
            return None
    result = total + section + num
    if result <= 0:
        return None
    return result


class CrossChecker:
    """读取 document_fields，按 cross_contract.yaml 执行勾稽。"""

    def __init__(self, db, document: Document, collector, options: dict | None = None):
        self.db = db
        self.document = document
        self.collector = collector
        self.options = options or {}

    def run(self) -> None:
        pack = load_cross_rules(self.document.doc_type)
        if not pack:
            self.collector.note_skipped("cross_rules")
            return

        rows = (
            self.db.query(DocumentField)
            .filter(DocumentField.document_id == self.document.id)
            .all()
        )
        fields = {f.field_key: f for f in rows}

        for rule in pack["checks"]:
            self._check_rule(rule, fields)

    # ---------------- 单条规则 ----------------

    def _check_rule(self, rule: dict, fields: dict[str, DocumentField]) -> None:
        fk = rule["id"]
        present = [k for k in rule["fields"] if k in fields]
        if len(present) != len(rule["fields"]):
            # 任一字段缺失：跳过，不误报
            return

        fn = getattr(self, f"_rule_{fk}", None)
        if fn is None:
            self.collector.add_warning(f"未知勾稽规则 {fk}，已跳过")
            return
        finding = fn(rule, fields)
        if finding is not None:
            self.collector.add(**finding)

    # 金额大写 = 小写
    def _rule_upper_vs_lower_amount(self, rule, fields) -> dict | None:
        lower = fields["total_amount"]
        upper = fields["amount_upper"]
        upper_num = chinese_upper_to_number(upper.value_text or "")
        if upper_num is None:
            # 大写无法解析：跳过（避免误报）
            return None
        if lower.value_number is None:
            return None
        if abs(upper_num - lower.value_number) < 0.01:
            return None
        return {
            "checker": "cross",
            "rule_id": rule["id"],
            "severity": rule["severity"],
            "message": rule["message"].format(
                lower=f"{lower.value_number:,.2f} 元", upper=upper.value_text),
            "suggestion": rule.get("suggestion"),
            "location": upper.location or lower.location,
        }

    # 单价 × 数量 = 总价
    def _rule_price_times_qty_total(self, rule, fields) -> dict | None:
        price = fields["unit_price"].value_number
        qty = fields["quantity"].value_number
        total = fields["total_amount"].value_number
        if price is None or qty is None or total is None or price <= 0:
            return None
        calc = price * qty
        tolerance = max(rule.get("tolerance_ratio", 0.01) * total, 0.01)
        if abs(calc - total) <= tolerance:
            return None
        return {
            "checker": "cross",
            "rule_id": rule["id"],
            "severity": rule["severity"],
            "message": rule["message"].format(
                price=fields["unit_price"].value_text,
                qty=fields["quantity"].value_text,
                calc=f"{calc:,.2f} 元",
                total=f"{total:,.2f} 元",
            ),
            "suggestion": rule.get("suggestion"),
            "location": fields["total_amount"].location,
        }

    # 签订日期 ≤ 交付日期
    def _rule_sign_before_delivery(self, rule, fields) -> dict | None:
        sign = fields["sign_date"].value_date
        delivery = fields["delivery_date"].value_date
        if sign is None or delivery is None:
            return None
        if sign <= delivery:
            return None
        return {
            "checker": "cross",
            "rule_id": rule["id"],
            "severity": rule["severity"],
            "message": rule["message"].format(
                sign=sign.date().isoformat(), delivery=delivery.date().isoformat()),
            "suggestion": rule.get("suggestion"),
            "location": fields["delivery_date"].location,
        }

    # 公告日期不早于签订日期
    def _rule_announce_after_sign(self, rule, fields) -> dict | None:
        sign = fields["sign_date"].value_date
        announce = fields["announce_date"].value_date
        if sign is None or announce is None:
            return None
        if announce >= sign:
            return None
        return {
            "checker": "cross",
            "rule_id": rule["id"],
            "severity": rule["severity"],
            "message": rule["message"].format(
                sign=sign.date().isoformat(), announce=announce.date().isoformat()),
            "suggestion": rule.get("suggestion"),
            "location": fields["announce_date"].location,
        }
