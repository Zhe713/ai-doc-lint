"""跨文档比对测试：CrossDocChecker 勾稽 + 比对组 API（创建/列表/详情/触发/删除）。"""

import uuid
from datetime import datetime
from types import SimpleNamespace

from app.checkers.cross_doc_checker import CrossDocChecker
from app.models.document import (
    CompareGroup,
    CompareGroupDocument,
    Document,
    DocumentField,
)
from conftest import TestSessionLocal
from tests.test_cross_checker import FakeCollector, _field, _money
from tests.test_intake import _auth, _make_user, _token


def _doc(db, username, *, doc_type="contract", status="parsed") -> Document:
    from app.models.user import User

    user = db.query(User).filter(User.username == username).one()
    doc = Document(
        user_id=user.id, filename="c.txt",
        storage_key=f"docs/{user.id}/orig.txt", sha256="x" * 64,
        size_bytes=100, content_type="text/plain",
        ext="txt", doc_type=doc_type, status=status,
    )
    db.add(doc)
    db.flush()
    return doc


def _setup_two_docs(fields_a: dict, fields_b: dict):
    """构造两份文档（同一用户）及其字段，返回 (db, doc_a, doc_b)。"""
    db = TestSessionLocal()
    username = f"cd_{uuid.uuid4().hex[:8]}"
    _make_user(username)
    doc_a = _doc(db, username)
    doc_b = _doc(db, username)
    db.commit()
    for doc, fields in ((doc_a, fields_a), (doc_b, fields_b)):
        for f in fields.values():
            f.document_id = doc.id
            db.add(f)
    db.commit()
    return db, doc_a, doc_b


def _by_doc(db, doc) -> dict[str, DocumentField]:
    rows = db.query(DocumentField).filter(
        DocumentField.document_id == doc.id).all()
    return {f.field_key: f for f in rows}


# ---------------- CrossDocChecker 单元 ----------------

def test_same_parties_no_findings():
    db, a, b = _setup_two_docs(
        {"party_a": _field("party_a", value_text="甲公司"),
         "party_b": _field("party_b", value_text="乙公司")},
        {"party_a": _field("party_a", value_text="甲公司"),
         "party_b": _field("party_b", value_text="乙公司")},
    )
    col = FakeCollector()
    CrossDocChecker(col, [a, b],
                    {str(a.id): _by_doc(db, a), str(b.id): _by_doc(db, b)}).run()
    assert col.finding_kwargs == []
    db.close()


def test_party_b_mismatch():
    db, a, b = _setup_two_docs(
        {"party_a": _field("party_a", value_text="甲公司"),
         "party_b": _field("party_b", value_text="乙公司")},
        {"party_a": _field("party_a", value_text="甲公司"),
         "party_b": _field("party_b", value_text="丙公司")},
    )
    col = FakeCollector()
    CrossDocChecker(col, [a, b],
                    {str(a.id): _by_doc(db, a), str(b.id): _by_doc(db, b)}).run()
    assert len(col.finding_kwargs) == 1  # 以 A 为主体报一条，对端 B
    f = col.finding_kwargs[0]
    assert f["rule_id"] == "party_b_consistent"
    assert f["severity"] == "error"
    assert f["related_document_id"] == b.id
    db.close()


def test_amount_mismatch_warning():
    db, a, b = _setup_two_docs(
        {"total_amount": _money("total_amount", "1000000元", 1000000.0)},
        {"total_amount": _money("total_amount", "800000元", 800000.0)},
    )
    col = FakeCollector()
    CrossDocChecker(col, [a, b],
                    {str(a.id): _by_doc(db, a), str(b.id): _by_doc(db, b)}).run()
    assert len(col.finding_kwargs) == 1
    f = col.finding_kwargs[0]
    assert f["rule_id"] == "total_amount_consistent"
    assert f["severity"] == "warning"
    assert f["related_document_id"] == b.id
    db.close()


def test_amount_within_tolerance_ok():
    # 差异 0.5% < 1% 容差：不报
    db, a, b = _setup_two_docs(
        {"total_amount": _money("total_amount", "1000000元", 1000000.0)},
        {"total_amount": _money("total_amount", "1005000元", 1005000.0)},
    )
    col = FakeCollector()
    CrossDocChecker(col, [a, b],
                    {str(a.id): _by_doc(db, a), str(b.id): _by_doc(db, b)}).run()
    assert col.finding_kwargs == []
    db.close()


def test_sign_date_sequence_warning():
    db, a, b = _setup_two_docs(
        {"sign_date": _field("sign_date", value_text="2026-08-21",
                             date=datetime(2026, 8, 21), value_type="date")},
        {"sign_date": _field("sign_date", value_text="2026-07-01",
                             date=datetime(2026, 7, 1), value_type="date")},
    )
    col = FakeCollector()
    CrossDocChecker(col, [a, b],
                    {str(a.id): _by_doc(db, a), str(b.id): _by_doc(db, b)}).run()
    assert len(col.finding_kwargs) == 1
    f = col.finding_kwargs[0]
    assert f["rule_id"] == "sign_date_sequence"
    assert f["related_document_id"] == a.id  # 后序文档 B 为主体，对端为首份 A
    db.close()


def test_missing_field_pair_skipped():
    db, a, b = _setup_two_docs(
        {"party_a": _field("party_a", value_text="甲公司")},
        {"total_amount": _money("total_amount", "1000000元", 1000000.0)},
    )
    col = FakeCollector()
    CrossDocChecker(col, [a, b],
                    {str(a.id): _by_doc(db, a), str(b.id): _by_doc(db, b)}).run()
    assert col.finding_kwargs == []
    db.close()


# ---------------- 比对组 API ----------------

def _upload_doc(client, headers, name="report.txt", content=b"hello"):
    resp = client.post(
        "/api/v1/documents/upload",
        files={"files": (name, content, "text/plain")},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["tasks"][0]["document_id"]


def test_compare_group_flow(client, monkeypatch):
    monkeypatch.setattr("app.api.documents.enqueue_parse", lambda task_id: None)
    monkeypatch.setattr("app.api.compare.enqueue_cross_compare", lambda task_id: None)
    headers = _auth(client, "cmp_owner")
    d1 = _upload_doc(client, headers, name="a.txt")
    d2 = _upload_doc(client, headers, name="b.txt")

    # 少于 2 份 → 422
    resp = client.post("/api/v1/compare-groups", headers=headers,
                       json={"name": "组A", "document_ids": [d1]})
    assert resp.status_code == 422

    # 非法文档 → 404
    resp = client.post("/api/v1/compare-groups", headers=headers,
                       json={"name": "组A",
                             "document_ids": [d1, str(uuid.uuid4())]})
    assert resp.status_code == 404

    # 正常创建
    resp = client.post("/api/v1/compare-groups", headers=headers,
                       json={"name": "主合同与补充协议", "document_ids": [d1, d2]})
    assert resp.status_code == 201, resp.text
    gid = resp.json()["id"]
    assert resp.json()["doc_count"] == 2

    # 列表
    resp = client.get("/api/v1/compare-groups", headers=headers)
    assert resp.status_code == 200
    assert any(g["id"] == gid for g in resp.json())

    # 触发比对
    resp = client.post(f"/api/v1/compare-groups/{gid}/compare", headers=headers)
    assert resp.status_code == 202, resp.text
    assert resp.json()["status"] == "queued"
    assert "task_id" in resp.json()

    # 详情
    resp = client.get(f"/api/v1/compare-groups/{gid}", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()["documents"]) == 2
    assert "matrix" in resp.json()
    assert "findings" in resp.json()

    # 删除
    resp = client.delete(f"/api/v1/compare-groups/{gid}", headers=headers)
    assert resp.status_code == 204
    resp = client.get(f"/api/v1/compare-groups/{gid}", headers=headers)
    assert resp.status_code == 404


def test_compare_group_ownership(client, monkeypatch):
    monkeypatch.setattr("app.api.documents.enqueue_parse", lambda task_id: None)
    h1 = _auth(client, "cmp_owner1")
    h2 = _auth(client, "cmp_owner2")
    d1 = _upload_doc(client, h1, name="a.txt")
    d2 = _upload_doc(client, h1, name="b.txt")
    resp = client.post("/api/v1/compare-groups", headers=h1,
                       json={"name": "私有组", "document_ids": [d1, d2]})
    gid = resp.json()["id"]
    # 他人不可见/不可删
    assert client.get(f"/api/v1/compare-groups/{gid}", headers=h2).status_code == 404
    assert client.delete(f"/api/v1/compare-groups/{gid}", headers=h2).status_code == 404
