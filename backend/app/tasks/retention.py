"""W9-1: 数据保留自动清理。

系统设置 data_retention_days（0 = 不自动清理）到期后，每日定时删除过期文档：
先删 MinIO 对象（文档原文 + 解析产物/批注），再删 DB 行（关联数据由外键 CASCADE 级联清理）。
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.db.session import SessionLocal
from app.db.storage import remove_object
from app.models.document import Artifact, Document
from app.services.setup_service import get_data_retention_days
from app.tasks.celery_app import celery_app

log = logging.getLogger("retention")


def _delete_document(db, doc: Document) -> int:
    """删除单个文档：先删 MinIO 对象，再删 DB 行（CASCADE 级联关联数据）。返回删除的 MinIO 对象数。"""
    removed = 0
    keys: list[str] = []
    for art in db.execute(select(Artifact).where(Artifact.document_id == doc.id)).scalars().all():
        if art.storage_key:
            keys.append(art.storage_key)
    if doc.storage_key:
        keys.append(doc.storage_key)
    for key in keys:
        try:
            remove_object(key)
            removed += 1
        except Exception:  # noqa: BLE001
            log.warning("remove MinIO object failed: %s", key)
    db.execute(delete(Document).where(Document.id == doc.id))
    return removed


@celery_app.task(name="app.tasks.retention.cleanup_expired_documents", ignore_result=True)
def cleanup_expired_documents() -> dict:
    """按 data_retention_days 删除过期文档。每日由 Beat 调度（默认 04:30，数据维护时段）。"""
    db = SessionLocal()
    deleted = 0
    removed_objects = 0
    try:
        days = get_data_retention_days(db)
        if not days or days <= 0:
            return {"enabled": False, "retention_days": days, "deleted": 0}
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        expired = db.execute(
            select(Document).where(Document.created_at < cutoff).order_by(Document.created_at)
        ).scalars().all()
        for doc in expired:
            removed_objects += _delete_document(db, doc)
            deleted += 1
            if deleted % 100 == 0:
                db.commit()
        db.commit()
        # W8 审计：数据清理留痕（动作级，不含文档内容）
        from app.services.audit_service import write_audit

        write_audit(db, action="retention_cleanup", username="system",
                    detail={"deleted": deleted, "removed_objects": removed_objects,
                            "retention_days": days})
        db.commit()
        log.info("retention cleanup: deleted=%d removed_objects=%d days=%s", deleted, removed_objects, days)
        return {"enabled": True, "retention_days": days, "deleted": deleted,
                "removed_objects": removed_objects}
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("retention cleanup failed")
        raise
    finally:
        db.close()
