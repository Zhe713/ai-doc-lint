"""W8: 审计写入服务 - 关键操作留痕（登录/上传/管理/学习闭环）。"""

import uuid

from sqlalchemy.orm import Session

from app.models.audit import AuditLog


def write_audit(
    db: Session,
    *,
    action: str,
    user_id: uuid.UUID | None = None,
    username: str | None = None,
    target: str | None = None,
    detail: dict | None = None,
    ip: str | None = None,
) -> None:
    """写一条审计日志。调用方负责 commit；同一 db 事务内与业务操作一致提交。"""
    db.add(
        AuditLog(
            user_id=user_id,
            username=username,
            action=action,
            target=target,
            detail=detail,
            ip=ip,
        )
    )
