"""批注版生成受理与产物下载接口（W4 Day18）。"""

import urllib.parse
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi import Response
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db import storage
from app.db.session import get_db
from app.models.document import Document, DocumentTask
from app.models.user import User
from app.services.annotate_service import create_annotate_task

router = APIRouter(tags=["annotate"])

DOCX_MIME = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


@router.post("/documents/{doc_id}/annotate", status_code=201)
def request_annotated(
    doc_id: uuid.UUID,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    doc = db.get(Document, doc_id)
    if doc is None or doc.user_id != current.id:
        raise HTTPException(status_code=404, detail="文档不存在")
    task = create_annotate_task(db, doc)
    return {"task_id": task.id, "document_id": doc.id, "status": task.status}


@router.get("/tasks/{task_id}/artifact")
def download_artifact(
    task_id: uuid.UUID,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    task = db.get(DocumentTask, task_id)
    if task is None or task.user_id != current.id:
        raise HTTPException(status_code=404, detail="任务不存在")

    refs = task.result_refs or {}
    key = refs.get("annotated")
    if not key:
        raise HTTPException(status_code=409, detail="产物尚未生成")

    doc = db.get(Document, task.document_id)
    data = storage.get_object_bytes(key)
    base = (doc.filename if doc else "document").rsplit(".", 1)[0]
    download_name = f"{base}_批注版.docx"
    quoted = urllib.parse.quote(download_name)
    return Response(
        content=data, media_type=DOCX_MIME,
        headers={
            "Content-Disposition":
                f"attachment; filename*=UTF-8''{quoted}",
        },
    )
