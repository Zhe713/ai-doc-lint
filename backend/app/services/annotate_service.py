"""annotate 任务受理：报告页请求生成批注版，建任务入 annotate 队列。"""

import logging

from sqlalchemy.orm import Session

from app.models.document import Document, DocumentTask, STATUS_PENDING

log = logging.getLogger("annotate")


def create_annotate_task(db: Session, document: Document) -> DocumentTask:
    task = DocumentTask(
        group_id=None,
        document_id=document.id,
        user_id=document.user_id,
        task_type="annotate",
        status=STATUS_PENDING,
        max_attempts=1,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    from app.tasks.annotate import enqueue_annotate

    enqueue_annotate(task.id)
    log.info("annotate task %s for document %s", task.id, document.id)
    return task
