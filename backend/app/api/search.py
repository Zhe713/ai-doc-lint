"""语义检索 API（W6 Day28）：/search + /documents/{id}/similar。"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.document import Document
from app.models.user import User
from app.services.search import search_chunks, similar_documents

router = APIRouter(tags=["search"])


@router.get("/search")
def semantic_search(
    q: str,
    limit: int = 10,
    mode: str = "hybrid",
    rerank: bool | None = None,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """检索相似条款/段落。

    mode=hybrid（默认）：向量 + 关键词 BM25 + RRF 融合，可本地精排；
    mode=semantic：纯向量语义检索（旧行为）。
    """
    if mode not in ("hybrid", "semantic"):
        raise HTTPException(status_code=400, detail="mode 仅支持 hybrid / semantic")
    results = search_chunks(db, current.id, q, limit, mode=mode, rerank=rerank)
    return {"query": q, "mode": mode, "total": len(results), "results": results}


@router.get("/documents/{document_id}/similar")
def document_similar(
    document_id: uuid.UUID,
    limit: int = 5,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    doc = db.get(Document, document_id)
    if doc is None or doc.user_id != current.id:
        raise HTTPException(status_code=404, detail="文档不存在")
    results = similar_documents(db, current.id, document_id, limit)
    return {"document_id": str(document_id), "total": len(results),
            "results": results}
