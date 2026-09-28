"""findings 查询/处理 schema。"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: UUID
    task_id: UUID | None
    checker: str
    rule_id: str
    severity: str
    location: dict | None
    message: str
    suggestion: str | None
    status: str
    created_at: datetime


class FindingPatch(BaseModel):
    status: str  # open / ignored / fixed


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    ext: str
    doc_type: str
    status: str
    size_bytes: int
    created_at: datetime
