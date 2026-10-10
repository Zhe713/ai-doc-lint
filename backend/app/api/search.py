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
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """按语义检索相似条款/段落；结果按余弦距离升序。"""
    results = search_chunks(db, current.id, q, limit)
    return {"query": q, "total": len(results), "results": results}


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
