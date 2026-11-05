"""Pydantic v2 请求/响应模型。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

USERNAME_PATTERN = r"^[A-Za-z0-9_\-\u4e00-\u9fa5]{3,32}$"


class SetupStatusOut(BaseModel):
    needs_setup: bool
    open_registration: bool


class SetupAdminIn(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def username_charset(cls, v: str) -> str:
        v = v.strip()
        import re

        if not re.match(USERNAME_PATTERN, v):
            raise ValueError("用户名需为3-32位，可包含中英文、数字、下划线、连字符")
        return v


class RegisterIn(SetupAdminIn):
    pass


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)


class RefreshIn(BaseModel):
    refresh_token: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RoleOut(BaseModel):
    name: str
    display_name: str

    model_config = {"from_attributes": True}


class UserOut(BaseModel):
    id: uuid.UUID
    username: str
    is_active: bool
    is_superuser: bool
    roles: list[str] = []
    created_at: datetime

    model_config = {"from_attributes": True}


class SettingsIn(BaseModel):
    open_registration: bool | None = None
    data_retention_days: int | None = Field(default=None, ge=0, le=3650)
    llm_daily_quota: int | None = Field(default=None, ge=0, le=100000)


class UserUpdateIn(BaseModel):
    """管理员修改用户：停用/启用、改角色、重置密码（三者可单独提交）。"""

    is_active: bool | None = None
    roles: list[str] | None = Field(default=None, description="角色名列表，如 ['admin']")
    password: str | None = Field(default=None, min_length=8, max_length=128)

    @field_validator("roles")
    @classmethod
    def roles_known(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        allowed = {"admin", "member"}
        unknown = [r for r in v if r not in allowed]
        if unknown:
            raise ValueError(f"未知角色：{', '.join(unknown)}")
        if not v:
            raise ValueError("至少要保留一个角色")
        return sorted(set(v))


class LLMUsageOut(BaseModel):
    used: int
    limit: int
    unlimited: bool
    remaining: int | None = None
    exhausted: bool = False
