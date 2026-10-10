"""语义检索服务（W6 Day28）：pgvector 余弦距离检索。

- search_chunks：查询文本向量化后按 chunk 级余弦距离取 Top-K；
- similar_documents：目标文档向量 = 其 chunks 均值，与库内其他文档均值向量比距离。
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.embed import EMBEDDING_DIM
from app.services.embedder import encode_one

_MAX_QUERY_CHARS = 500


def search_chunks(db: Session, user_id: uuid.UUID, query: str,
                  limit: int = 10) -> list[dict]:
    """语义检索：返回 [{document_id, filename, chunk_index, content, distance}]。"""
    query = (query or "").strip()[: _MAX_QUERY_CHARS]
    if not query:
        return []
    limit = max(1, min(int(limit), 50))
    vec = encode_one(query)
    if len(vec) != EMBEDDING_DIM:
        raise RuntimeError(f"embedding dim mismatch: {len(vec)} != {EMBEDDING_DIM}")
    sql = text(
        """
        SELECT c.document_id, d.filename, d.doc_type,
               c.chunk_index, c.content,
               c.embedding <=> CAST(:q_vec AS vector) AS distance
        FROM document_chunks c
        JOIN documents d ON d.id = c.document_id AND d.user_id = :uid
        ORDER BY c.embedding <=> CAST(:q_vec AS vector)
        LIMIT :limit
        """
    )
    rows = db.execute(sql, {"q_vec": vec, "uid": user_id, "limit": limit}).all()
    return [
        {
            "document_id": str(r.document_id),
            "filename": r.filename,
            "doc_type": r.doc_type,
            "chunk_index": r.chunk_index,
            "content": r.content,
            "distance": round(float(r.distance), 4),
        }
        for r in rows
    ]


def similar_documents(db: Session, user_id: uuid.UUID, document_id: uuid.UUID,
                      limit: int = 5) -> list[dict]:
    """找与目标文档语义最相似的其它文档（文档级均值向量距离）。"""
    limit = max(1, min(int(limit), 20))
    sql = text(
        """
        WITH target AS (
            SELECT document_id, avg(embedding) AS v
            FROM document_chunks
            WHERE document_id = :doc_id
            GROUP BY document_id
        )
        SELECT d.id, d.filename, d.doc_type,
               (avg(c.embedding) <=> (SELECT v FROM target)) AS distance
        FROM document_chunks c
        JOIN documents d ON d.id = c.document_id AND d.user_id = :uid
        WHERE c.document_id != :doc_id
          AND EXISTS (SELECT 1 FROM target)
        GROUP BY d.id, d.filename, d.doc_type
        ORDER BY (avg(c.embedding) <=> (SELECT v FROM target))
        LIMIT :limit
        """
    )
    rows = db.execute(sql, {"doc_id": document_id, "uid": user_id,
                            "limit": limit}).all()
    return [
        {
            "document_id": str(r.id),
            "filename": r.filename,
            "doc_type": r.doc_type,
            "distance": round(float(r.distance), 4),
        }
        for r in rows
    ]
