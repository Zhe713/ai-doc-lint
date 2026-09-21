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
