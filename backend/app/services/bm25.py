"""轻量 BM25 关键词检索（P2 混合检索组件之一）。

- 纯 Python 实现，无外部分词依赖：中文段按 2-gram（单字保留）+ 英文/数字整词切分；
- 极小停用词表过滤虚词；
- 索引按 chunk 构建（每个 chunk 视为一篇“文档”），进程内按用户 + 数据版本缓存；
- 数据版本 = 用户文档与 chunk 的最新 updated_at，变更即失效重建。
"""

from __future__ import annotations

import logging
import math
import re
import threading
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session

log = logging.getLogger("bm25")

_K1 = 1.2
_B = 0.75

# 轻量中文停用词（虚词/助词，对条款检索无判别力）
_STOP = frozenset(
    "的了在是有和就都与这那及或等之于为对以并其该所而但且如由从向把被将按依按据经依据按照通过根据双方甲方乙方各方当事人合同协议本份下述下列上述"
)

_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+|[a-zA-Z0-9]+")


def tokenize(text: str) -> list[str]:
    """中文段 -> 2-gram + 单字；英文/数字 -> 整词小写。"""
    tokens: list[str] = []
    for seg in _TOKEN_RE.findall(text or ""):
        if seg.isascii():
            w = seg.lower()
            if len(w) >= 2 or w.isdigit():
                tokens.append(w)
            continue
        # 中文段
        if len(seg) == 1:
            if seg not in _STOP:
                tokens.append(seg)
            continue
        for i in range(len(seg) - 1):
            g = seg[i:i + 2]
            if g not in _STOP:
                tokens.append(g)
    return tokens


@dataclass
class BM25Index:
    """统计型 BM25 索引，只读后复用。"""

    doc_count: int
    avgdl: float
    df: dict[str, int] = field(default_factory=dict)
    doc_freqs: list[dict[str, int]] = field(default_factory=list)
    doc_lens: list[int] = field(default_factory=list)

    def idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log((self.doc_count - df + 0.5) / (df + 0.5) + 1.0)

    def score(self, query_terms: list[str]) -> list[float]:
        scores = [0.0] * self.doc_count
        for t in set(query_terms):
            idf = self.idf(t)
            if idf <= 0:
                continue
            for i, freqs in enumerate(self.doc_freqs):
                f = freqs.get(t, 0)
                if not f:
                    continue
                dl = self.doc_lens[i]
                denom = f + _K1 * (1 - _B + _B * dl / self.avgdl)
                scores[i] += idf * (f * (_K1 + 1)) / denom
        return scores

    def search(self, query: str, top_k: int) -> list[int]:
        terms = tokenize(query)
        if not terms:
            return []
        scores = self.score(terms)
        ranked = sorted(range(self.doc_count), key=lambda i: scores[i], reverse=True)
        return [i for i in ranked if scores[i] > 0][:top_k]


def _build(chunks: list[tuple[int, str]]) -> BM25Index:
    """chunks: [(doc_position, content)]；position 与返回下标对应。"""
    doc_freqs: list[dict[str, int]] = []
    doc_lens: list[int] = []
    df: dict[str, int] = {}
    for _, content in chunks:
        tokens = tokenize(content)
        freq: dict[str, int] = {}
        for t in tokens:
            freq[t] = freq.get(t, 0) + 1
        doc_freqs.append(freq)
        doc_lens.append(len(tokens))
        for t in freq:
            df[t] = df.get(t, 0) + 1
    n = len(chunks)
    avgdl = sum(doc_lens) / n if n else 0.0
    return BM25Index(doc_count=n, avgdl=avgdl, df=df,
                     doc_freqs=doc_freqs, doc_lens=doc_lens)


# 进程内缓存：user_id -> (data_version, index)
_CACHE: dict[str, tuple[str, BM25Index]] = {}
_LOCK = threading.Lock()


def _data_version(db: Session, user_id: str) -> str:
    row = db.execute(
        text(
            """
            SELECT COALESCE(MAX(d.updated_at), 'epoch')::text || '#' ||
                   COALESCE(MAX(c.created_at), 'epoch')::text AS ver
            FROM documents d
            LEFT JOIN document_chunks c ON c.document_id = d.id
            WHERE d.user_id = :uid
            """
        ),
        {"uid": user_id},
    ).scalar_one_or_none()
    return row or ""


def get_index(db: Session, user_id: str) -> tuple[BM25Index, list[dict]]:
    """取用户 BM25 索引 + 位置元数据（data_version 变更时重建）。"""
    with _LOCK:
        ver = _data_version(db, user_id)
        cached = _CACHE.get(user_id)
        if cached and cached[0] == ver:
            return cached[1], _chunk_meta(db, user_id)
    rows = db.execute(
        text(
            """
            SELECT c.document_id, d.filename, d.doc_type, c.chunk_index, c.content
            FROM document_chunks c
            JOIN documents d ON d.id = c.document_id AND d.user_id = :uid
            ORDER BY d.created_at, c.chunk_index
            """
        ),
        {"uid": user_id},
    ).all()
    chunks = [(i, r.content) for i, r in enumerate(rows)]
    idx = _build(chunks)
    with _LOCK:
        _CACHE[user_id] = (ver, idx)
    return idx, _chunk_meta(db, user_id)


def _chunk_meta(db: Session, user_id: str) -> list[dict]:
    rows = db.execute(
        text(
            """
            SELECT c.document_id, d.filename, d.doc_type, c.chunk_index, c.content
            FROM document_chunks c
            JOIN documents d ON d.id = c.document_id AND d.user_id = :uid
            ORDER BY d.created_at, c.chunk_index
            """
        ),
        {"uid": user_id},
    ).all()
    return [
        {
            "document_id": str(r.document_id),
            "filename": r.filename,
            "doc_type": r.doc_type,
            "chunk_index": r.chunk_index,
            "content": r.content,
        }
        for r in rows
    ]


def search_keyword(db: Session, user_id: str, query: str, top_k: int) -> list[dict]:
    """BM25 关键词检索：返回 [{document_id, filename, doc_type, chunk_index, content, bm25_score}]。"""
    idx, meta = get_index(db, user_id)
    if not idx.doc_count:
        return []
    terms = tokenize(query)
    if not terms:
        return []
    scores = idx.score(terms)
    positions = idx.search(query, top_k)
    out = []
    for i in positions:
        m = meta[i]
        out.append({**m, "bm25_score": round(float(scores[i]), 4)})
    return out
