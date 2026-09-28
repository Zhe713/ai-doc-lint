"""review 任务受理：parse 完成后为文档创建校验任务并入 review 队列。

review 任务不挂任务组（group_id=None），不影响上传批次的组计数。
"""

import logging

from sqlalchemy.orm import Session

from app.models.document import Document, DocumentTask, STATUS_PENDING

log = logging.getLogger("review")


def create_review_task(
    db: Session,
    document: Document,
    *,
    checks: list[str] | None = None,
    doc_type_hint: str | None = None,
) -> DocumentTask:
    task = DocumentTask(
        group_id=None,
        document_id=document.id,
        user_id=document.user_id,
        task_type="review",
        status=STATUS_PENDING,
        max_attempts=1,
        stats={"checks": checks or [], "doc_type_hint": doc_type_hint or document.doc_type},
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    from app.tasks.review import enqueue_review

    enqueue_review(task.id)
    log.info("review task %s enqueued for document %s", task.id, document.id)
    return task
