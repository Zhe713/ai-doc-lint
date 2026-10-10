"""cross_compare（跨文档比对）任务：组内文档两两勾稽，findings 入表（带 related_document_id）。

文档字段缺失时先跑 FieldExtractor（allow_llm=True 补抽），再进行确定性勾稽。
"""

import logging
import uuid

from app.db.session import SessionLocal
from app.models.document import (
    STATUS_PENDING,
    CompareGroup,
    CompareGroupDocument,
    Document,
    DocumentField,
    DocumentTask,
)
from app.services import task_state
from app.tasks.celery_app import QUEUE_CROSS_COMPARE, celery_app
from app.tasks.events import append_event
from app.tasks.review_pipeline import FindingCollector, summarize

logger = logging.getLogger("cross_compare")
log = logging.getLogger("cross_compare")


def enqueue_cross_compare(task_id: uuid.UUID) -> None:
    run_cross_compare.apply_async(args=[str(task_id)], queue=QUEUE_CROSS_COMPARE)


def _load_fields(db, document: Document) -> dict[str, DocumentField]:
    """读取文档字段；为空则先跑 FieldExtractor 补抽，返回 field_key -> row。"""
    rows = (
        db.query(DocumentField)
        .filter(DocumentField.document_id == document.id)
        .all()
    )
    if not rows:
        from app.extract.field_extractor import FieldExtractor

        FieldExtractor(db, document, allow_llm=True).run()
        db.commit()
        rows = (
            db.query(DocumentField)
            .filter(DocumentField.document_id == document.id)
            .all()
        )
    return {f.field_key: f for f in rows}


@celery_app.task(name="app.tasks.cross_compare.run_cross_compare",
                 bind=True, max_retries=2)
def run_cross_compare(self, task_id_str: str):
    db = SessionLocal()
    try:
        task = db.get(DocumentTask, uuid.UUID(task_id_str))
        if task is None:
            log.warning("cross_compare task %s not found, skip", task_id_str)
            return
        if task.status != STATUS_PENDING:
            log.info("cross_compare task %s status %s, skip", task_id_str, task.status)
            return

        task_state.change_status(
            db, task, task_state.STATUS_RUNNING,
            event_type="task_started", stage="init",
            message="开始跨文档比对",
            fields={"celery_task_id": self.request.id},
        )

        stats = task.stats or {}
        group_id = stats.get("compare_group_id")
        group = db.get(CompareGroup, uuid.UUID(group_id)) if group_id else None
        if group is None:
            task_state.change_status(
                db, task, task_state.STATUS_FAILED,
                event_type="task_failed", stage="error",
                message="比对组不存在",
            )
            return

        links = (
            db.query(CompareGroupDocument)
            .filter(CompareGroupDocument.compare_group_id == group.id)
            .order_by(CompareGroupDocument.position)
            .all()
        )
        doc_ids = [l.document_id for l in links]
        docs = [db.get(Document, did) for did in doc_ids]
        docs = [d for d in docs if d is not None]
        if len(docs) < 2:
            task_state.change_status(
                db, task, task_state.STATUS_FAILED,
                event_type="task_failed", stage="error",
                message="比对组内有效文档不足 2 份",
            )
            return

        append_event(db, task, "stage_progress", stage="extract",
                     message=f"共 {len(docs)} 份文档参与比对，开始字段补抽/比对")
        db.commit()

        fields_by_doc = {str(d.id): _load_fields(db, d) for d in docs}

        collector = FindingCollector(db, task)
        from app.checkers.cross_doc_checker import CrossDocChecker

        CrossDocChecker(collector, docs, fields_by_doc).run()
        collector.flush()
        db.commit()

        stats_out = {
            **summarize(collector.items, collector.skipped, collector.warnings),
            "doc_count": len(docs),
            "compare_group_id": str(group.id),
        }
        group.status = STATUS_PARSED
        group.stats = stats_out
        db.commit()

        task_state.change_status(
            db, task, STATUS_PARSED,
            event_type="task_succeeded", stage="done",
            message="跨文档比对完成",
            fields={"stats": stats_out},
        )
        log.info("cross_compare task %s done: %s findings",
                 task_id_str, stats_out.get("total", 0))
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("cross_compare task %s failed: %s", task_id_str, exc)
        raise self.retry(exc=exc, countdown=5)
    finally:
        db.close()
