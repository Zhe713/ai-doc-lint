"""首次启动初始化与系统设置读写。"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.models.user import Role, SystemSetting, User, UserRole

ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"

ROLE_DEFS = {
    ROLE_ADMIN: "管理员",
    ROLE_MEMBER: "普通成员",
}

SETTING_OPEN_REGISTRATION = "open_registration"
SETTING_DATA_RETENTION = "data_retention_days"
SETTING_LLM_QUOTA = "llm_daily_quota"


def ensure_roles(db: Session) -> dict[str, Role]:
    roles: dict[str, Role] = {}
    for name, display_name in ROLE_DEFS.items():
        role = db.scalar(select(Role).where(Role.name == name))
        if role is None:
            role = Role(name=name, display_name=display_name)
            db.add(role)
            db.flush()
        roles[name] = role
    db.commit()
    return roles


def has_admin(db: Session) -> bool:
    """是否已存在拥有 admin 角色的用户（与是否有普通成员无关）。"""
    stmt = (
        select(func.count())
        .select_from(User)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(Role.name == ROLE_ADMIN)
    )
    return db.scalar(stmt) > 0


def needs_setup(db: Session) -> bool:
    # 只要还没有管理员就视为未初始化；普通成员注册不应锁死初始化入口
    return not has_admin(db)


def get_setting(db: Session, key: str):
    row = db.get(SystemSetting, key)
    return row.value if row else None


def is_registration_open(db: Session) -> bool:
    value = get_setting(db, SETTING_OPEN_REGISTRATION)
    if value is None:
        return settings.open_registration
    return bool(value)


def get_data_retention_days(db: Session) -> int | None:
    """数据保留期限（天）；None 表示不自动清理。"""
    value = get_setting(db, SETTING_DATA_RETENTION)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def get_llm_daily_quota(db: Session) -> int | None:
    """每日智能审查调用限额；None 表示不限制。"""
    value = get_setting(db, SETTING_LLM_QUOTA)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def set_setting(db: Session, key: str, value, updated_by: uuid.UUID | None = None) -> None:
    row = db.get(SystemSetting, key)
    if row is None:
        row = SystemSetting(key=key, value=value, updated_by=updated_by)
        db.add(row)
    else:
        row.value = value
        row.updated_by = updated_by
    db.commit()


def create_initial_admin(db: Session, username: str, password: str) -> User:
    """仅在系统中没有任何用户时允许创建首个管理员。"""
    if not needs_setup(db):
        raise ValueError("系统已初始化，不能重复创建管理员")
    roles = ensure_roles(db)
    admin = User(
        username=username.strip(),
        password_hash=hash_password(password),
        is_active=True,
        is_superuser=True,
    )
    db.add(admin)
    db.flush()
    db.add(UserRole(user_id=admin.id, role_id=roles[ROLE_ADMIN].id))
    set_setting(db, SETTING_OPEN_REGISTRATION, settings.open_registration, updated_by=admin.id)
    db.commit()
    db.refresh(admin)
    return admin
