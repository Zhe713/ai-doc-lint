"""混合检索服务（P2）：pgvector 向量 + BM25 关键词 + RRF 融合 + 本地 reranker。

- search_chunks：hybrid 模式 = 向量 Top-K ∪ BM25 Top-K → RRF 融合 → 可选 reranker 精排；
  semantic 模式保留纯向量检索（与旧行为一致）；
- similar_documents：文档级均值向量距离（沿用）。
"""

from __future__ import annotations

import math
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.embed import EMBEDDING_DIM
from app.services import reranker as reranker_svc
from app.services.bm25 import search_keyword
from app.services.embedder import encode_one

_MAX_QUERY_CHARS = 500
_RRF_K = 60


def _finite(value: float | None) -> float | None:
    """NaN/Inf 转 None（零向量余弦距离会返回 NaN）。"""
    if value is None:
        return None
    f = float(value)
    return f if math.isfinite(f) else None


def _vector_search(db: Session, user_id: uuid.UUID, vec: list[float], limit: int) -> list[dict]:
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
    rows = db.execute(sql, {"q_vec": vec, "uid": str(user_id), "limit": limit}).all()
    out = []
    for r in rows:
        d = _finite(r.distance)
        out.append({
            "document_id": str(r.document_id),
            "filename": r.filename,
            "doc_type": r.doc_type,
            "chunk_index": r.chunk_index,
            "content": r.content,
            "distance": round(d, 4) if d is not None else None,
        })
    return out


def _rrf_fuse(vector_hits: list[dict], bm25_hits: list[dict], top_k: int = 60) -> list[dict]:
    """RRF 融合：score = Σ 1/(K + rank)；去重同 (document_id, chunk_index)。"""
    fused: dict[tuple, dict] = {}
    score_map: dict[tuple, float] = {}

    def key(h: dict) -> tuple:
        return (h["document_id"], h["chunk_index"])

    for rank, h in enumerate(vector_hits, start=1):
        k = key(h)
        score_map[k] = score_map.get(k, 0.0) + 1.0 / (_RRF_K + rank)
        fused.setdefault(k, {**h, "vector_distance": _finite(h.get("distance")),
                             "bm25_score": None, "rrf_score": 0.0})
    for rank, h in enumerate(bm25_hits, start=1):
        k = key(h)
        score_map[k] = score_map.get(k, 0.0) + 1.0 / (_RRF_K + rank)
        if k not in fused:
            fused[k] = {**h, "vector_distance": None, "bm25_score": h.get("bm25_score"),
                        "rrf_score": 0.0}
        else:
            fused[k]["bm25_score"] = h.get("bm25_score")
    for k, s in score_map.items():
        fused[k]["rrf_score"] = round(float(s), 6)
    ranked = sorted(fused.values(), key=lambda x: x["rrf_score"], reverse=True)
    return ranked[:top_k]


def search_chunks(db: Session, user_id: uuid.UUID, query: str,
                  limit: int = 10, mode: str = "hybrid",
                  rerank: bool | None = None) -> list[dict]:
    """混合/语义检索。

    mode: hybrid（默认，向量+BM25+RRF）| semantic（纯向量）
    rerank: None 跟随配置 hybrid_rerank_enabled；显式 True/False 覆盖。
    """
    query = (query or "").strip()[: _MAX_QUERY_CHARS]
    if not query:
        return []
    limit = max(1, min(int(limit), 50))
    vec = encode_one(query)
    if len(vec) != EMBEDDING_DIM:
        raise RuntimeError(f"embedding dim mismatch: {len(vec)} != {EMBEDDING_DIM}")

    if mode == "semantic":
        return _vector_search(db, user_id, vec, limit)

    vector_hits = _vector_search(db, user_id, vec, settings.hybrid_vector_topk)
    bm25_hits = search_keyword(db, str(user_id), query, settings.hybrid_bm25_topk)
    fused = _rrf_fuse(vector_hits, bm25_hits, top_k=max(limit, settings.hybrid_rerank_topn))

    do_rerank = settings.hybrid_rerank_enabled if rerank is None else rerank
    if do_rerank and fused:
        try:
            fused = reranker_svc.rerank(query, fused, settings.hybrid_rerank_topn)
        except Exception:  # noqa: BLE001  reranker 降级，RRF 顺序仍可用
            pass
    return fused[:limit]


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
    rows = db.execute(sql, {"doc_id": str(document_id), "uid": str(user_id),
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
