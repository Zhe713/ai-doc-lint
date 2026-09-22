"""解析任务（W2 Day6：骨架走通队列与状态机；Day8 替换为 docling 真实解析）。

真实解析阶段（下载/格式探测/docling 抽取/置信度/OCR/标准化）在 Day 8 接入，
本周 dummy 版本完整走通：入队→RUNNING→阶段事件→PARSED，以及闸门挂起骨架。
"""

import logging
import uuid

from celery.utils.log import get_task_logger

from app.db.session import SessionLocal
from app.models.document import (
    STATUS_AWAITING,
    STATUS_PENDING,
    DocumentTask,
)
from app.services import task_state
from app.tasks.celery_app import celery_app
from app.tasks.events import append_event

logger = get_task_logger(__name__)
log = logging.getLogger("parse")


def _check_cancelled(db, task: DocumentTask) -> bool:
    """协作式取消：排队中/运行中被用户取消则跳出流水线。"""
    db.refresh(task)
    return task.status == task_state.STATUS_CANCELLED


@celery_app.task(name="app.tasks.parse.run_parse", bind=True, max_retries=3)
def run_parse(self, task_id_str: str):
    db = SessionLocal()
    try:
        task = db.get(DocumentTask, uuid.UUID(task_id_str))
        if task is None:
            log.warning("task %s not found, skip", task_id_str)
            return
        if task.status not in (STATUS_PENDING, STATUS_AWAITING):
            log.info("task %s in status %s, skip", task_id_str, task.status)
            return

        task_state.change_status(
            db, task, task_state.STATUS_RUNNING,
            event_type="task_started", stage="init",
            message="开始受理解析", fields={"celery_task_id": self.request.id},
        )

        # --- 阶段事件（Day6 占位；Day8 在此替换为 docling 真实流程） ---
        for stage, msg in [
            ("download", "从对象存储读取原件"),
            ("extract", "文本/结构抽取（Day8 接 docling）"),
            ("normalize", "生成标准化产物"),
        ]:
            if _check_cancelled(db, task):
                log.info("task %s cancelled, stop pipeline", task_id_str)
                return
            append_event(db, task, "stage_progress", stage=stage, message=msg)
            db.commit()

        stats = {
            "stages_completed": ["download", "extract", "normalize"],
            "placeholder": True,  # Day8 替换为页数/字数/表数/置信度/ocr_used
        }
        task_state.change_status(
            db, task, task_state.STATUS_PARSED,
            event_type="task_succeeded", stage="done",
            message="解析完成（骨架）",
            fields={"stats": stats, "result_refs": {"note": "artifacts 在 Day8 写入"}},
        )
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("parse task %s failed: %s", task_id_str, exc)
        # 瞬时错误退避重试（Day8 细化错误分类；内容错误走闸门而非重试）
        raise self.retry(exc=exc, countdown=5)
    finally:
        db.close()
