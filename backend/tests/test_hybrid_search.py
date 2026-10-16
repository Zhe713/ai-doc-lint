"""P2 混合检索测试：BM25 分词/索引/检索 + RRF 融合 + 接口冒烟。"""

import uuid

import pytest

from app.models.document import Document
from app.services import search as search_svc
from app.services.bm25 import tokenize


# ---------- BM25 分词 ----------

def test_tokenize_chinese_bigram():
    toks = tokenize("付款条款：合同签订后支付预付款")
    assert "付款" in toks and "款条" in toks and "条款" in toks
    # 停用词不产生无判别力的单字/虚词对
    assert "合同" in toks  # 常用词也保留（2-gram），仅过滤极小停用词集合


def test_tokenize_english_and_digits():
    toks = tokenize("违约金 10% penalty CLAUSE 2026")
    assert "penalty" in toks
    assert "clause" in toks
    assert "10" in toks
    assert "2026" in toks


def test_tokenize_empty():
    assert tokenize("") == []
    assert tokenize("！！！") == []


# ---------- BM25 索引检索 ----------

def test_bm25_index_ranks_relevant_first():
    from app.services.bm25 import _build

    idx = _build([
        (0, "付款条款：合同签订后支付预付款，预付款比例为合同金额的30%"),
        (1, "违约责任：违约金为合同金额的10%，逾期每日万分之五"),
        (2, "知识产权归属：甲方享有全部权利，乙方不得擅自使用"),
    ])
    hits = idx.search("违约金", 3)
    assert len(hits) > 0
    # 唯一含“违约金”的 chunk1 应排最前
    assert hits[0] == 1
    # 精确词命中应高于无关 chunk（0 分不返回）
    assert 2 not in hits


# ---------- RRF 融合 ----------

def test_rrf_fuse_merges_and_ranks():
    vector_hits = [
        {"document_id": "a", "chunk_index": 0, "content": "x", "distance": 0.1},
        {"document_id": "b", "chunk_index": 0, "content": "y", "distance": 0.2},
    ]
    bm25_hits = [
        {"document_id": "b", "chunk_index": 0, "content": "y", "bm25_score": 3.0},
        {"document_id": "c", "chunk_index": 0, "content": "z", "bm25_score": 2.0},
    ]
    fused = search_svc._rrf_fuse(vector_hits, bm25_hits, top_k=10)
    assert len(fused) == 3
    # 双通道命中的 b 排最前，且去重后只有一条
    assert fused[0]["document_id"] == "b"
    assert fused[0]["rrf_score"] > fused[1]["rrf_score"]
    assert fused[0]["vector_distance"] == 0.2
    assert fused[0]["bm25_score"] == 3.0


# ---------- 接口冒烟（hybrid / semantic / rerank 关闭） ----------

@pytest.fixture()
def search_env(monkeypatch):
    from app.core.security import hash_password
    from app.models.user import User
    from conftest import TestSessionLocal

    db = TestSessionLocal()
    try:
        u = User(username=f"hybrid_{uuid.uuid4().hex[:8]}",
                 password_hash=hash_password("MemberPass123"))
        db.add(u)
        db.commit()
        db.refresh(u)
        uid = u.id
        d1 = Document(user_id=uid, filename="采购合同.txt", storage_key="k/1",
                      sha256=uuid.uuid4().hex, size_bytes=10, ext="txt",
                      doc_type="contract", status="parsed")
        d2 = Document(user_id=uid, filename="保密协议.txt", storage_key="k/2",
                      sha256=uuid.uuid4().hex, size_bytes=10, ext="txt",
                      doc_type="contract", status="parsed")
        db.add_all([d1, d2])
        db.commit()
        db.refresh(d1)
        db.refresh(d2)

        from app.models.embed import DocumentChunk
        vec = [0.0] * 512
        db.add_all([
            DocumentChunk(document_id=d1.id, chunk_index=0,
                          content="付款条款：合同签订后支付预付款",
                          embedding=vec),
            DocumentChunk(document_id=d1.id, chunk_index=1,
                          content="违约责任：违约金为合同金额的 10%",
                          embedding=vec),
            DocumentChunk(document_id=d2.id, chunk_index=0,
                          content="保密义务：乙方对甲方商业秘密承担保密责任",
                          embedding=vec),
        ])
        db.commit()
    finally:
        db.close()

    def fake_encode_one(text: str) -> list[float]:
        v = [0.0] * 512
        v[0] = float(hash("付款条款：合同签订后支付预付款") % 100) / 100.0
        v[1] = 0.0
        return v

    monkeypatch.setattr("app.services.search.encode_one", fake_encode_one)
    return {"user_id": uid, "d1": d1, "d2": d2}


def _auth(client, username: str):
    from app.models.user import User
    from conftest import TestSessionLocal
    from tests.test_intake import _make_user, _token

    db = TestSessionLocal()
    try:
        exists = db.query(User).filter(User.username == username).first()
    finally:
        db.close()
    if exists is None:
        _make_user(username)
    return {"Authorization": f"Bearer {_token(client, username)}"}


def test_hybrid_search_api(client, search_env):
    from conftest import TestSessionLocal
    from app.models.user import User

    db = TestSessionLocal()
    try:
        u = db.query(User).filter(User.id == search_env["user_id"]).first()
        uname = u.username
    finally:
        db.close()
    headers = _auth(client, uname)

    # hybrid 关闭 rerank（避免测试环境加载模型）
    r = client.get("/api/v1/search?q=违约金&limit=3&mode=hybrid&rerank=false",
                   headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "hybrid"
    assert body["total"] >= 1
    assert body["results"][0]["content"] == "违约责任：违约金为合同金额的 10%"

    # semantic 兼容旧行为
    r2 = client.get("/api/v1/search?q=付款条款&limit=3&mode=semantic",
                    headers=headers)
    assert r2.status_code == 200
    assert r2.json()["mode"] == "semantic"

    # 非法 mode
    r3 = client.get("/api/v1/search?q=x&mode=bad", headers=headers)
    assert r3.status_code == 400
