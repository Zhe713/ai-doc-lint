"""W6 Day28：语义检索 API + pgvector 查询（mock embedding）。"""

import uuid

import pytest

from app.models.document import Document
from conftest import TestSessionLocal


def _mk_user(name: str | None = None) -> uuid.UUID:
    from app.core.security import hash_password
    from app.models.user import User

    db = TestSessionLocal()
    try:
        u = User(username=name or f"search_{uuid.uuid4().hex[:8]}",
                 password_hash=hash_password("MemberPass123"))
        db.add(u)
        db.commit()
        db.refresh(u)
        return u.id
    finally:
        db.close()


def _mk_doc(user_id: uuid.UUID, name: str) -> Document:
    db = TestSessionLocal()
    try:
        d = Document(user_id=user_id, filename=name, storage_key=f"k/{name}",
                     sha256=uuid.uuid4().hex, size_bytes=10, ext="txt",
                     doc_type="contract", status="parsed")
        db.add(d)
        db.commit()
        db.refresh(d)
        return d
    finally:
        db.close()


def _mk_chunk(user_id: uuid.UUID, doc: Document, idx: int, content: str,
              dim: int = 512):
    db = TestSessionLocal()
    try:
        from app.models.embed import DocumentChunk

        vec = [0.0] * dim
        # 给内容打上可区分的向量：内容 hash 决定首元素，保证距离有区分度
        vec[0] = float(hash(content) % 100) / 100.0
        vec[1] = float(idx) / 100.0
        c = DocumentChunk(document_id=doc.id, chunk_index=idx,
                          content=content, embedding=vec)
        db.add(c)
        db.commit()
    finally:
        db.close()


@pytest.fixture()
def search_env(monkeypatch):
    uname = f"search_owner_{uuid.uuid4().hex[:8]}"
    uid = _mk_user(uname)
    d1 = _mk_doc(uid, "合同A.txt")
    d2 = _mk_doc(uid, "合同B.txt")
    _mk_chunk(uid, d1, 0, "付款条款：合同签订后支付预付款")
    _mk_chunk(uid, d1, 1, "违约责任：违约金为合同金额的 10%")
    _mk_chunk(uid, d2, 0, "知识产权归属：甲方享有全部权利")

    # mock 查询向量：返回与 chunk0（付款条款）最接近的向量
    def fake_encode_one(text: str) -> list[float]:
        v = [0.0] * 512
        v[0] = float(hash("付款条款：合同签订后支付预付款") % 100) / 100.0
        v[1] = 0.0
        return v

    monkeypatch.setattr("app.services.search.encode_one", fake_encode_one)
    yield {"user_id": uid, "username": uname, "doc1": d1, "doc2": d2}


def _auth(client, username: str):
    from app.models.user import User
    from tests.test_intake import _make_user, _token

    db = TestSessionLocal()
    try:
        exists = db.query(User).filter(User.username == username).first()
    finally:
        db.close()
    if exists is None:
        _make_user(username)
    return {"Authorization": f"Bearer {_token(client, username)}"}


def test_search_api_returns_top_chunk(client, search_env):
    headers = _auth(client, search_env["username"])
    r = client.get("/api/v1/search?q=付款条款&limit=3", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 1
    top = body["results"][0]
    assert "付款条款" in top["content"]
    assert top["document_id"] == str(search_env["doc1"].id)


def test_search_empty_query(client, search_env):
    headers = _auth(client, search_env["username"])
    r = client.get("/api/v1/search?q=", headers=headers)
    assert r.status_code == 200
    assert r.json()["total"] == 0
