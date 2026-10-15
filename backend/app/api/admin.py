"""管理员接口：用户列表、系统设置、审计日志、系统健康。"""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.core.ratelimit import get_redis
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import SettingsIn, UserOut
from app.services import auth_service, setup_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db), _: User = Depends(require_admin)
) -> list[dict]:
    users = db.scalars(select(User).order_by(User.created_at.desc())).all()
    return [auth_service.user_public(u) for u in users]


@router.get("/settings")
def read_settings(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict:
    return {
        "open_registration": setup_service.is_registration_open(db),
        "data_retention_days": setup_service.get_data_retention_days(db),
        "llm_daily_quota": setup_service.get_llm_daily_quota(db),
    }


@router.patch("/settings")
def update_settings(
    body: SettingsIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    changes: dict[str, object] = {}
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
    if body.llm_daily_quota is not None:
        setup_service.set_setting(
            db, setup_service.SETTING_LLM_QUOTA, body.llm_daily_quota, updated_by=admin.id
        )
        changes["llm_daily_quota"] = body.llm_daily_quota
    # W8 审计：系统设置变更留痕
    from app.services.audit_service import write_audit

    if changes:
        write_audit(db, action="admin_setting", user_id=admin.id,
                    username=admin.username, detail=changes)
    db.commit()
    return {
        "open_registration": setup_service.is_registration_open(db),
        "data_retention_days": setup_service.get_data_retention_days(db),
        "llm_daily_quota": setup_service.get_llm_daily_quota(db),
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


@router.get("/system/stats")
def system_stats(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict:
    """管理员系统健康页：文档/任务/队列/依赖/审计概况。"""
    from app.api.monitoring import _db_stats, _queue_lengths
    from app.models.audit import AuditLog

    db_stats = _db_stats()
    db_stats["queues"] = _queue_lengths()
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
