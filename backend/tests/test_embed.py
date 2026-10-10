"""W6 Day27：分块器 + embed 任务（mock 模型与存储，0 下载）。"""

import uuid

import pytest

from app.models.document import (
    STATUS_FAILED,
    STATUS_PARSED,
    Document,
    DocumentTask,
)
from app.services.chunker import chunk_text
from conftest import TestSessionLocal

SAMPLE = """甲方：东莞市教育局
乙方：某某建设有限公司

第一条 付款方式
合同签订后 30 日内支付 30% 预付款。

第二条 违约责任
任何一方违约应当赔偿对方损失。

第三条 争议解决
提交有管辖权的人民法院解决。"""


def _user() -> uuid.UUID:
    from app.models.user import User
    from app.core.security import hash_password

    db = TestSessionLocal()
    try:
        u = User(username=f"embed_{uuid.uuid4().hex[:8]}",
                 password_hash=hash_password("MemberPass123"))
        db.add(u)
        db.commit()
        db.refresh(u)
        return u.id
    finally:
        db.close()


def _doc(user_id: uuid.UUID) -> Document:
    db = TestSessionLocal()
    try:
        d = Document(
            user_id=user_id, filename="demo.txt", storage_key="x",
            sha256=uuid.uuid4().hex, size_bytes=100, ext="txt",
            doc_type="contract", status="parsed",
        )
        db.add(d)
        db.commit()
        db.refresh(d)
        return d
    finally:
        db.close()


# ---- 分块器 ----

def test_chunker_empty():
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


LONG_SAMPLE = "\n".join(
    f"第{i}条 条款内容：本合同由甲方与乙方签订，约定付款方式与违约责任。"
    for i in range(30)
)


def test_chunker_splits_paragraphs():
    chunks = chunk_text(LONG_SAMPLE, target=200, overlap=20)
    assert len(chunks) >= 3
    assert all(len(c) <= 220 for c in chunks)
    assert "第0条" in chunks[0]


def test_chunker_hard_splits_long_para():
    # 递增编号避免切块内容雷同被去重
    long_para = "".join(f"第{i}段条款内容" for i in range(800))  # ~6000 字符单段
    chunks = chunk_text(long_para, target=500, overlap=50)
    assert len(chunks) >= 7
    assert all(len(c) <= 510 for c in chunks)


def test_chunker_no_duplicates():
    text = "甲\n乙\n甲\n丙\n乙"
    chunks = chunk_text(text, target=10, overlap=0)
    assert len(chunks) == len(set(chunks))


# ---- embed 任务 ----

@pytest.fixture()
def embed_doc():
    uid = _user()
    doc = _doc(uid)
    yield doc
    db = TestSessionLocal()
    try:
        from app.models.embed import DocumentChunk

        db.query(DocumentChunk).delete()
        db.query(DocumentTask).delete()
        db.query(Document).filter(Document.id == doc.id).delete()
        db.commit()
    finally:
        db.close()


def test_create_embed_task_idempotent(embed_doc, monkeypatch):
    monkeypatch.setattr("app.tasks.embed.enqueue_embed", lambda tid: None)
    db = TestSessionLocal()
    try:
        from app.tasks.embed import create_embed_task

        t1 = create_embed_task(db, embed_doc)
        t2 = create_embed_task(db, embed_doc)
        assert t1 is not None
        assert t2 is None  # 第二次幂等跳过
    finally:
        db.close()


def test_do_embed_writes_chunks(embed_doc, monkeypatch):
    monkeypatch.setattr("app.tasks.embed.encode",
                        lambda texts, batch_size=32: [[0.1] * 512 for _ in texts])

    db = TestSessionLocal()
    try:
        from app.tasks.embed import _do_embed

        chunks = chunk_text(SAMPLE)
        stats = _do_embed(db, embed_doc, chunks)
        assert stats["chunks"] == len(chunks)
        assert stats["dim"] == 512

        from app.models.embed import DocumentChunk

        rows = (db.query(DocumentChunk)
                .filter(DocumentChunk.document_id == embed_doc.id)
                .order_by(DocumentChunk.chunk_index).all())
        assert len(rows) == len(chunks)
        assert len(rows[0].embedding) == 512
        assert "付款方式" in rows[0].content
    finally:
        db.close()


def test_do_embed_idempotent_rewrite(embed_doc, monkeypatch):
    """重复向量化先清旧块再写，不产生重复。"""
    monkeypatch.setattr("app.tasks.embed.encode",
                        lambda texts, batch_size=32: [[0.2] * 512 for _ in texts])
    db = TestSessionLocal()
    try:
        from app.tasks.embed import _do_embed

        chunks1 = chunk_text(SAMPLE)
        chunks2 = chunk_text(SAMPLE + "\n\n补充条款：另行约定。")
        _do_embed(db, embed_doc, chunks1)
        _do_embed(db, embed_doc, chunks2)

        from app.models.embed import DocumentChunk

        count = db.query(DocumentChunk).filter(
            DocumentChunk.document_id == embed_doc.id).count()
        assert count == len(chunks2)
    finally:
        db.close()
