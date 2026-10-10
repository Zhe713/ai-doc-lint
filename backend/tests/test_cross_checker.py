"""CrossChecker 测试：中文大写转数字、金额/数量/日期勾稽、字段缺失跳过。"""

import uuid
from datetime import datetime

from app.checkers.cross_checker import (
    CrossChecker,
    chinese_upper_to_number,
)
from app.models.document import Document, DocumentField
from conftest import TestSessionLocal
from tests.test_intake import _make_user


class FakeCollector:
    def __init__(self):
        self.items = []
        self.skipped = []
        self.warnings = []
        self.finding_kwargs = []

    def add(self, **kw):
        self.finding_kwargs.append(kw)
        return kw

    def note_skipped(self, rule):
        self.skipped.append(rule)

    def add_warning(self, message):
        self.warnings.append(message)


def _field(field_key, *, value_text=None, number=None, date=None,
           value_type="string", label=None):
    return DocumentField(
        document_id=uuid.uuid4(), field_key=field_key,
        field_label=label or field_key, value_type=value_type,
        value_text=value_text, value_number=number, value_date=date,
        source="rule", confidence=1.0,
    )


def _money(key: str, text: str, number: float) -> DocumentField:
    return _field(key, value_text=text, number=number, value_type="money")


def _setup(fields: dict[str, DocumentField], doc_type="contract"):
    db = TestSessionLocal()
    username = f"cross_{uuid.uuid4().hex[:8]}"
    _make_user(username)
    from app.models.user import User

    user = db.query(User).filter(User.username == username).one()
    doc = Document(
        user_id=user.id, filename="c.txt",
        storage_key=f"docs/{user.id}/orig.txt", sha256="x" * 64,
        size_bytes=100, content_type="text/plain",
        ext="txt", doc_type=doc_type, status="parsed",
    )
    db.add(doc)
    db.flush()  # 生成 doc.id（default 在 flush 时惰性生成）
    for f in fields.values():
        f.document_id = doc.id
        db.add(f)
    db.commit()
    return db, doc


# ---------------- 中文大写转数字 ----------------

def test_chinese_upper_to_number():
    assert chinese_upper_to_number("壹佰贰拾叁万肆仟伍佰陆拾柒元整") == 1234567.0
    assert chinese_upper_to_number("伍拾万元整") == 500000.0
    assert chinese_upper_to_number("壹仟元整") == 1000.0
    assert chinese_upper_to_number("人民币壹佰零捌万伍仟元整") == 1085000.0
    assert chinese_upper_to_number("玖佰玖拾玖元玖角玖分") is None  # 角分暂不支持
    assert chinese_upper_to_number("") is None
    assert chinese_upper_to_number("abc") is None


# ---------------- 金额大小写勾稽 ----------------

def test_amount_upper_matches_lower():
    db, doc = _setup({
        "total_amount": _money("total_amount", "1085000元", 1085000.0),
        "amount_upper": _field("amount_upper",
                               value_text="壹佰零捌万伍仟元整"),
    })
    col = FakeCollector()
    CrossChecker(db, doc, col).run()
    assert col.finding_kwargs == []
    db.close()


def test_amount_upper_mismatch():
    db, doc = _setup({
        "total_amount": _money("total_amount", "2000000元", 2000000.0),
        "amount_upper": _field("amount_upper",
                               value_text="壹佰零捌万伍仟元整"),
    })
    col = FakeCollector()
    CrossChecker(db, doc, col).run()
    assert len(col.finding_kwargs) == 1
    f = col.finding_kwargs[0]
    assert f["rule_id"] == "upper_vs_lower_amount"
    assert f["severity"] == "error"
    assert "壹佰零捌万伍仟元整" in f["message"]
    db.close()


def test_upper_unparseable_skips():
    # 大写含角分（暂不支持解析）：跳过不误报
    db, doc = _setup({
        "total_amount": _money("total_amount", "999元", 999.0),
        "amount_upper": _field("amount_upper",
                               value_text="玖佰玖拾玖元玖角玖分"),
    })
    col = FakeCollector()
    CrossChecker(db, doc, col).run()
    assert col.finding_kwargs == []
    db.close()


# ---------------- 单价×数量=总价 ----------------

def test_price_qty_total_consistent():
    db, doc = _setup({
        "unit_price": _money("unit_price", "1085000元", 1085000.0),
        "quantity": _field("quantity", value_text="1批", number=1.0,
                           value_type="number"),
        "total_amount": _money("total_amount", "1085000元", 1085000.0),
    })
    col = FakeCollector()
    CrossChecker(db, doc, col).run()
    assert col.finding_kwargs == []
    db.close()


def test_price_qty_total_mismatch():
    db, doc = _setup({
        "unit_price": _money("unit_price", "500元", 500.0),
        "quantity": _field("quantity", value_text="10件", number=10.0,
                           value_type="number"),
        "total_amount": _money("total_amount", "4000元", 4000.0),
    })
    col = FakeCollector()
    CrossChecker(db, doc, col).run()
    assert len(col.finding_kwargs) == 1
    f = col.finding_kwargs[0]
    assert f["rule_id"] == "price_times_qty_total"
    assert f["severity"] == "error"
    assert "5,000.00" in f["message"]  # 计算值 500*10
    db.close()


def test_price_qty_rounding_tolerance():
    # 5000*2=10000 vs 9999.99：1% 容差内不报
    db, doc = _setup({
        "unit_price": _money("unit_price", "5000元", 5000.0),
        "quantity": _field("quantity", value_text="2", number=2.0,
                           value_type="number"),
        "total_amount": _money("total_amount", "9999.99元", 9999.99),
    })
    col = FakeCollector()
    CrossChecker(db, doc, col).run()
    assert col.finding_kwargs == []
    db.close()


# ---------------- 日期勾稽 ----------------

def test_sign_before_delivery_ok():
    db, doc = _setup({
        "sign_date": _field("sign_date", value_text="2026-08-21",
                            date=datetime(2026, 8, 21), value_type="date"),
        "delivery_date": _field("delivery_date", value_text="2026-09-01",
                                date=datetime(2026, 9, 1), value_type="date"),
    })
    col = FakeCollector()
    CrossChecker(db, doc, col).run()
    assert col.finding_kwargs == []
    db.close()


def test_sign_after_delivery_warning():
    db, doc = _setup({
        "sign_date": _field("sign_date", value_text="2026-10-01",
                            date=datetime(2026, 10, 1), value_type="date"),
        "delivery_date": _field("delivery_date", value_text="2026-09-01",
                                date=datetime(2026, 9, 1), value_type="date"),
    })
    col = FakeCollector()
    CrossChecker(db, doc, col).run()
    assert len(col.finding_kwargs) == 1
    f = col.finding_kwargs[0]
    assert f["rule_id"] == "sign_before_delivery"
    assert f["severity"] == "warning"
    db.close()


# ---------------- 字段缺失与无包 ----------------

def test_missing_fields_skip():
    # 只有 total_amount，没有 amount_upper：跳过不报
    db, doc = _setup({
        "total_amount": _money("total_amount", "1085000元", 1085000.0),
    })
    col = FakeCollector()
    CrossChecker(db, doc, col).run()
    assert col.finding_kwargs == []
    db.close()


def test_no_pack_skipped():
    db, doc = _setup({"total_amount": _money("total_amount", "1元", 1.0)},
                     doc_type="general")
    col = FakeCollector()
    CrossChecker(db, doc, col).run()
    assert "cross_rules" in col.skipped
    assert col.finding_kwargs == []
    db.close()
