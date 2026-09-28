"""任务状态机：集中定义合法跳转，任何代码不得直接改 status 绕过这里。

并发安全：状态更新使用 `WHERE id=:id AND status=:from` 条件更新（乐观守卫），
组内计数用 SQL 级增减（pending = pending - 1），避免读改写竞争。
"""

from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models.document import (
    STATUS_AWAITING,
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_PARSED,
    STATUS_PENDING,
    STATUS_RETRYING,
    STATUS_RUNNING,
    Document,
    DocumentTask,
    TaskGroup,
)
from app.tasks.events import append_event


class IllegalTransition(Exception):
    pass


# 合法跳转表
LEGAL: dict[str, set[str]] = {
    STATUS_PENDING: {STATUS_RUNNING, STATUS_CANCELLED, STATUS_FAILED},
    STATUS_RUNNING: {STATUS_PARSED, STATUS_AWAITING, STATUS_RETRYING, STATUS_FAILED, STATUS_CANCELLED},
    STATUS_RETRYING: {STATUS_RUNNING, STATUS_FAILED},
    STATUS_AWAITING: {STATUS_PENDING, STATUS_PARSED, STATUS_CANCELLED},
    STATUS_PARSED: set(),
    STATUS_FAILED: set(),
    STATUS_CANCELLED: set(),
}

# 组内计数桶（retrying 并入 running 统计）
_BUCKET = {
    STATUS_PENDING: "pending",
    STATUS_RUNNING: "running",
    STATUS_RETRYING: "running",
    STATUS_AWAITING: "awaiting",
    STATUS_PARSED: "succeeded",
    STATUS_FAILED: "failed",
    STATUS_CANCELLED: "cancelled",
}


def _bump_group(db: Session, task: DocumentTask, from_status: str, to_status: str) -> None:
    if task.group_id is None:
        return
    old_bucket, new_bucket = _BUCKET[from_status], _BUCKET[to_status]
    if old_bucket == new_bucket:
        return
    db.execute(
        update(TaskGroup)
        .where(TaskGroup.id == task.group_id)
        .values(
            **{old_bucket: getattr(TaskGroup, old_bucket) - 1},
            **{new_bucket: getattr(TaskGroup, new_bucket) + 1},
        )
    )


def change_status(
    db: Session,
    task: DocumentTask,
    to_status: str,
    *,
    event_type: str,
    stage: str | None = None,
    message: str | None = None,
    payload: dict | None = None,
    fields: dict | None = None,
    commit: bool = True,
) -> None:
    """原子地把任务从 task.status 切到 to_status，非法跳转抛 IllegalTransition。"""
    from_status = task.status
    if to_status not in LEGAL[from_status]:
        raise IllegalTransition(f"{from_status} -> {to_status} 非法")

    values: dict = {"status": to_status}
    now = datetime.now(timezone.utc)
    if to_status == STATUS_RUNNING and from_status in (STATUS_PENDING, STATUS_RETRYING, STATUS_AWAITING):
        values["started_at"] = now
    if to_status in (STATUS_PARSED, STATUS_FAILED, STATUS_CANCELLED, STATUS_AWAITING):
        values["finished_at"] = now
    if fields:
        values.update(fields)

    result = db.execute(
        update(DocumentTask).where(DocumentTask.id == task.id, DocumentTask.status == from_status).values(**values)
    )
    if result.rowcount != 1:
        # 并发下已被别的协程改掉，刷新后视为冲突
        db.rollback()
        raise IllegalTransition(f"任务 {task.id} 状态已被并发修改，跳转 {from_status}->{to_status} 中止")

    _bump_group(db, task, from_status, to_status)
    # 文档主档状态只跟随 parse 任务；review/annotate/learn 不覆盖解析结果状态
    if task.task_type == "parse":
        db.execute(update(Document).where(Document.id == task.document_id).values(status=to_status))

    # 整组全部进入终态时记录批次完成时间
    if task.group_id is not None:
        group = db.get(TaskGroup, task.group_id)
        if group is not None and group.finished_at is None:
            settled = group.succeeded + group.failed + group.cancelled
            if settled >= group.total and group.pending == 0 and group.running == 0 and group.awaiting == 0:
                db.execute(
                    update(TaskGroup).where(TaskGroup.id == group.id).values(finished_at=now)
                )

    # 同步到内存对象，便于事件 payload 读取
    for k, v in values.items():
        setattr(task, k, v)

    append_event(db, task, event_type, stage=stage, message=message, payload=payload)

    if commit:
        db.commit()
