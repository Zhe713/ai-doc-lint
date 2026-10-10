"""规则包自定义（W6 Day26）：管理员上传/启停 YAML 规则包。

pack_type 与 loader 的 4 类加载器对应：
- format：格式规则（doc_type 固定 "global"）
- clause：条款完整性
- field：字段抽取
- cross：交叉勾稽
启用中的同类型自定义包优先于内置 yaml（见 checkers/loader.py）。
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

PACK_FORMAT = "format"
PACK_CLAUSE = "clause"
PACK_FIELD = "field"
PACK_CROSS = "cross"
PACK_TYPES = (PACK_FORMAT, PACK_CLAUSE, PACK_FIELD, PACK_CROSS)

GLOBAL_DOC_TYPE = "global"


class RulePack(Base):
    __tablename__ = "rule_packs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    pack_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    doc_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default=GLOBAL_DOC_TYPE, index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    yaml_content: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False)
