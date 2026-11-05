"""管理员接口：用户管理（读写）、系统设置、LLM 用量、审计日志、系统健康。"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.core.ratelimit import get_redis
from app.core.security import hash_password
from app.db.session import get_db
from app.models.user import User, UserRole
from app.schemas.auth import SettingsIn, UserOut, UserUpdateIn
from app.services import auth_service, setup_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db), _: User = Depends(require_admin)
) -> list[dict]:
    users = db.scalars(select(User).order_by(User.created_at.desc())).all()
    return [auth_service.user_public(u) for u in users]


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: uuid.UUID,
    body: UserUpdateIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    """停用/启用、改角色、重置密码。

    三条保护，缺一条都会让管理员把自己或系统锁死：
    1. 不能停用自己、不能取消自己的管理员角色；
    2. 不能停用/降级最后一个可用管理员；
    3. 改角色采用「全量替换」，避免遗留脏角色。
    """
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    is_self = user.id == admin.id
    changes: dict[str, object] = {}

    if body.is_active is not None and body.is_active != user.is_active:
        if is_self and not body.is_active:
            raise HTTPException(status_code=409, detail="不能停用当前登录的管理员账号")
        user.is_active = body.is_active
        changes["is_active"] = body.is_active

    if body.roles is not None:
        roles = setup_service.ensure_roles(db)
        current = set(user.role_names)
        target = set(body.roles)
        if is_self and "admin" in current and "admin" not in target:
            raise HTTPException(status_code=409, detail="不能取消自己的管理员角色")
        if "admin" in current and "admin" not in target:
            others = db.execute(
                select(func.count(func.distinct(UserRole.user_id)))
                .join(User, User.id == UserRole.user_id)
                .where(
                    UserRole.role_id == roles["admin"].id,
                    UserRole.user_id != user.id,
                    User.is_active.is_(True),
                )
            ).scalar_one()
            if others == 0:
                raise HTTPException(
                    status_code=409,
                    detail="系统至少需要保留一名可用管理员，请先指定另一位管理员",
                )
        if target != current:
            db.query(UserRole).filter(UserRole.user_id == user.id).delete()
            for name in target:
                db.add(UserRole(user_id=user.id, role_id=roles[name].id))
            changes["roles"] = sorted(target)

    if body.password:
        user.password_hash = hash_password(body.password)
        changes["password"] = "reset"

    if changes:
        from app.services.audit_service import write_audit

        write_audit(db, action="admin_user_update", user_id=admin.id,
                    username=admin.username, target=user.username, detail=changes)
    db.commit()
    db.refresh(user)
    return auth_service.user_public(user)


@router.get("/llm-usage")
def llm_usage(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict:
    """当日智能审查额度用量（与设置页同一口径：调用次数/天）。"""
    from app.llm.client import llm_usage_today

    return llm_usage_today(db)


@router.get("/settings")
def read_settings(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict:
    from app.llm.client import llm_usage_today

    return {
        "open_registration": setup_service.is_registration_open(db),
        "data_retention_days": setup_service.get_data_retention_days(db),
        "llm_daily_quota": setup_service.get_llm_daily_quota(db),
        "llm_usage": llm_usage_today(db),
    }


@router.patch("/settings")
def update_settings(
    body: SettingsIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    changes: dict[str, object] = {}
    # 显式传 null 表示「清空该项回到默认」，与「没传这个字段」区分开
    sent = body.model_fields_set
    if body.open_registration is not None:
        setup_service.set_setting(
            db, setup_service.SETTING_OPEN_REGISTRATION, body.open_registration, updated_by=admin.id
        )
        changes["open_registration"] = body.open_registration
    if body.data_retention_days is not None:
        setup_service.set_setting(
            db, setup_service.SETTING_DATA_RETENTION, body.data_retention_days, updated_by=admin.id
        )
        changes["data_retention_days"] = body.data_retention_days
    elif "data_retention_days" in sent:
        setup_service.clear_setting(db, setup_service.SETTING_DATA_RETENTION)
        changes["data_retention_days"] = "默认"
    if body.llm_daily_quota is not None:
        setup_service.set_setting(
            db, setup_service.SETTING_LLM_QUOTA, body.llm_daily_quota, updated_by=admin.id
        )
        changes["llm_daily_quota"] = body.llm_daily_quota
    elif "llm_daily_quota" in sent:
        setup_service.clear_setting(db, setup_service.SETTING_LLM_QUOTA)
        changes["llm_daily_quota"] = "不限"
    # W8 审计：系统设置变更留痕
    from app.services.audit_service import write_audit

    if changes:
        write_audit(db, action="admin_setting", user_id=admin.id,
                    username=admin.username, detail=changes)
    db.commit()
    from app.llm.client import llm_usage_today

    return {
        "open_registration": setup_service.is_registration_open(db),
        "data_retention_days": setup_service.get_data_retention_days(db),
        "llm_daily_quota": setup_service.get_llm_daily_quota(db),
        "llm_usage": llm_usage_today(db),
    }


@router.get("/audit-logs")
def list_audit_logs(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
    action: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """W8 审计日志查询（管理员）：按动作过滤 + 分页。"""
    from sqlalchemy import func, select

    from app.models.audit import AuditLog

    q = select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    cq = select(func.count(AuditLog.id))
    if action:
        q = q.where(AuditLog.action == action)
        cq = cq.where(AuditLog.action == action)
    total = db.execute(cq).scalar_one()
    rows = db.execute(q.limit(limit).offset(offset)).scalars().all()
    return {
        "total": total,
        "items": [
            {
                "id": r.id,
                "username": r.username,
                "action": r.action,
                "target": r.target,
                "detail": r.detail,
                "ip": r.ip,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.get("/alerts")
def list_alerts(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
) -> dict:
    """W9 系统告警查询（管理员）：按状态过滤 + 分页。"""
    from app.models.alert import AlertEvent

    q = select(AlertEvent).order_by(AlertEvent.created_at.desc(), AlertEvent.id.desc())
    cq = select(func.count(AlertEvent.id))
    if status:
        q = q.where(AlertEvent.status == status)
        cq = cq.where(AlertEvent.status == status)
    total = db.execute(cq).scalar_one()
    rows = db.execute(q.limit(limit).offset(offset)).scalars().all()
    return {
        "total": total,
        "items": [
            {
                "id": str(r.id),
                "level": r.level,
                "alert_type": r.alert_type,
                "message": r.message,
                "detail": r.detail,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
            }
            for r in rows
        ],
    }


@router.get("/system/stats")
def system_stats(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict:
    """管理员系统健康页：文档/任务/队列/依赖/审计概况。"""
    from app.api.monitoring import _db_stats, _queue_lengths
    from app.models.alert import AlertEvent
    from app.models.audit import AuditLog

    db_stats = _db_stats()
    db_stats["queues"] = _queue_lengths()
    db_stats["alerts_active"] = db.execute(
        select(func.count(AlertEvent.id)).where(AlertEvent.status == "active")
    ).scalar_one()
    db_stats["recent_audit"] = db.execute(
        select(func.count(AuditLog.id)).where(
            AuditLog.created_at >= func.now() - func.make_interval(0, 0, 0, 1)
        )
    ).scalar_one()
    # 依赖探活（复用 /health 逻辑的轻量版）
    try:
        from app.core.config import settings
        from app.db.storage import minio_client

        db_stats["valkey"] = "ok" if get_redis().ping() else "error"
        db_stats["minio"] = "ok" if minio_client.bucket_exists(settings.minio_bucket) else "error"
    except Exception as exc:  # noqa: BLE001
        db_stats["deps"] = f"error: {type(exc).__name__}"
    return db_stats
