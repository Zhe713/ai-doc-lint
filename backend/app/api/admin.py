"""管理员接口：用户列表、系统设置。"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import require_admin
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
    if body.open_registration is not None:
        setup_service.set_setting(
            db, setup_service.SETTING_OPEN_REGISTRATION, body.open_registration, updated_by=admin.id
        )
    if body.data_retention_days is not None:
        setup_service.set_setting(
            db, setup_service.SETTING_DATA_RETENTION, body.data_retention_days, updated_by=admin.id
        )
    if body.llm_daily_quota is not None:
        setup_service.set_setting(
            db, setup_service.SETTING_LLM_QUOTA, body.llm_daily_quota, updated_by=admin.id
        )
    return {
        "open_registration": setup_service.is_registration_open(db),
        "data_retention_days": setup_service.get_data_retention_days(db),
        "llm_daily_quota": setup_service.get_llm_daily_quota(db),
    }
