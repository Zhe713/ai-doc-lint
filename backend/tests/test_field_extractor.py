"""FieldExtractor 测试：规则抽取与归一化、LLM 补抽、反幻觉丢弃、无包跳过。"""

import json
import uuid
from types import SimpleNamespace

from app.db import storage
from app.extract.field_extractor import FieldExtractor
from app.models.document import Artifact, Document, DocumentField
from conftest import TestSessionLocal
from tests.test_intake import _make_user

# 字段齐全的公告：13 个字段全部可被规则命中（0 token）
FULL_ANNOUNCEMENT = """政府采购合同公告详情
一、合同编号： FHZB-2026009
二、合同名称： 营养餐食材采购项目
三、项目编号： FHZB-2026009-XM
四、项目名称： 营养餐食材采购项目
五、合同主体
采购人（甲方）： 铜川市教育局新区分局
供应商（乙方）： 陕西马咀优选生鲜供应链有限责任公司
六、合同主要信息
主要标的数量：1.0000批
主要标的单价：1085000.0000元
合同金额： 108.500000万元
金额大写：人民币壹佰零捌万伍仟元整
七、合同签订日期： 2026-08-21
八、合同公告日期： 2026-10-08
九、交付日期： 2026-09-01 前交付
"""

# 缺少交付日期的公告（规则层抽不到 delivery_date）
BASE_ANNOUNCEMENT = "\n".join(
    line for line in FULL_ANNOUNCEMENT.splitlines()
    if not line.startswith("九、")
)


def _setup(doc_text: str, *, doc_type="contract"):
    db = TestSessionLocal()
    username = f"field_{uuid.uuid4().hex[:8]}"
    _make_user(username)
    from app.models.user import User

    user = db.query(User).filter(User.username == username).one()
    doc = Document(
        user_id=user.id, filename="c.txt",
        storage_key=f"docs/{user.id}/orig.txt", sha256="x" * 64,
        size_bytes=len(doc_text), content_type="text/plain",
        ext="txt", doc_type=doc_type, status="parsed",
    )
    db.add(doc)
    db.flush()
    key = f"artifacts/{doc.id}/plaintext.txt"
    storage.put_object(key, doc_text.encode("utf-8"),
                       content_type="text/plain")
    db.add(Artifact(document_id=doc.id, kind="plaintext",
                    storage_key=key))
    db.commit()
    return db, doc


def test_rule_extraction_normalized(monkeypatch):
    called = []
    monkeypatch.setattr(
        "app.extract.field_extractor.chat",
        lambda *a, **k: called.append(1) or SimpleNamespace(
            content='{"fields": []}'),
    )
    db, doc = _setup(FULL_ANNOUNCEMENT)
    fields = FieldExtractor(db, doc, allow_llm=True).run()
    by_key = {f.field_key: f for f in fields}

    assert by_key["contract_no"].value_text == "FHZB-2026009"
    assert by_key["project_no"].value_text == "FHZB-2026009-XM"
    assert by_key["party_a"].value_text == "铜川市教育局新区分局"
    assert by_key["party_b"].value_text == "陕西马咀优选生鲜供应链有限责任公司"
    assert by_key["amount_upper"].value_text == "壹佰零捌万伍仟元整"
    # 金额归一化为元
    assert by_key["unit_price"].value_number == 1085000.0
    assert by_key["total_amount"].value_number == 1085000.0
    assert by_key["quantity"].value_number == 1.0
    assert by_key["sign_date"].value_date.year == 2026
    assert by_key["sign_date"].value_date.month == 8
    assert by_key["delivery_date"].value_date.day == 1
    assert len(fields) == 13
    assert all(f.source == "rule" for f in fields)
    assert called == []  # 全部规则命中，0 token
    db.close()


def test_fields_persisted_and_upsert(monkeypatch):
    monkeypatch.setattr("app.extract.field_extractor.chat",
                        lambda *a, **k: SimpleNamespace(content="{}"))
    db, doc = _setup(FULL_ANNOUNCEMENT)
    FieldExtractor(db, doc, allow_llm=False).run()
    first_n = db.query(DocumentField).filter(
        DocumentField.document_id == doc.id).count()
    # 再跑一次：upsert，不产生重复
    FieldExtractor(db, doc, allow_llm=False).run()
    second_n = db.query(DocumentField).filter(
        DocumentField.document_id == doc.id).count()
    assert first_n == second_n
    assert first_n == 13
    db.close()


def test_llm_fallback_with_valid_quote(monkeypatch):
    # 不含“交付日期/期限/时间”等规则触发词，规则层抽不到；LLM 引用真实存在于原文
    extra = "于2026年9月10日前送到指定地点"
    payload = json.dumps({"fields": [
        {"key": "delivery_date", "value": "2026-09-10",
         "quote": extra},
    ]}, ensure_ascii=False)
    monkeypatch.setattr("app.extract.field_extractor.chat",
                        lambda *a, **k: SimpleNamespace(content=payload))
    db, doc = _setup(BASE_ANNOUNCEMENT + extra + "\n")
    fields = FieldExtractor(db, doc, allow_llm=True).run()
    delivery = next(f for f in fields if f.field_key == "delivery_date")
    assert delivery.source == "llm"
    assert delivery.confidence == 0.7
    assert delivery.value_date.day == 10
    db.close()


def test_llm_hallucinated_quote_discarded(monkeypatch):
    payload = json.dumps({"fields": [
        {"key": "delivery_date", "value": "2026-09-01",
         "quote": "原文中完全不存在的一句话"},
    ]}, ensure_ascii=False)
    monkeypatch.setattr("app.extract.field_extractor.chat",
                        lambda *a, **k: SimpleNamespace(content=payload))
    db, doc = _setup(BASE_ANNOUNCEMENT)
    extractor = FieldExtractor(db, doc, allow_llm=True)
    fields = extractor.run()
    assert all(f.field_key != "delivery_date" for f in fields)
    assert any("无法在原文匹配" in w for w in extractor.warnings)
    db.close()


def test_llm_duplicate_key_deduped(monkeypatch):
    """LLM 对同一字段输出多条（大小写不同）：应去重取第一条，不撞唯一约束。"""
    # 去掉“合同名称”行，让 contract_title 进入 LLM 补抽
    no_title = "\n".join(
        line for line in BASE_ANNOUNCEMENT.splitlines()
        if "合同名称" not in line
    )
    extra = "\nThis Co-Promotion Agreement is made between the parties."
    payload = json.dumps({"fields": [
        {"key": "contract_title", "value": "Co-Promotion Agreement",
         "quote": "This Co-Promotion Agreement"},
        {"key": "contract_title", "value": "CO-PROMOTION AGREEMENT",
         "quote": "CO-PROMOTION AGREEMENT"},
    ]}, ensure_ascii=False)
    monkeypatch.setattr("app.extract.field_extractor.chat",
                        lambda *a, **k: SimpleNamespace(content=payload))
    db, doc = _setup(no_title + extra)
    fields = FieldExtractor(db, doc, allow_llm=True).run()
    titles = [f for f in fields if f.field_key == "contract_title"]
    assert len(titles) == 1
    assert titles[0].value_text == "Co-Promotion Agreement"
    assert titles[0].source == "llm"
    db.close()


def test_no_pack_returns_empty():
    db, doc = _setup(FULL_ANNOUNCEMENT, doc_type="general")
    fields = FieldExtractor(db, doc, allow_llm=True).run()
    assert fields == []
    db.close()
