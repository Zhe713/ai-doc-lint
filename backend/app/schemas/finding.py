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
    feedback_reason: str | None = None
    feedback_cause: str | None = None
    created_at: datetime


class FindingPatch(BaseModel):
    status: str  # open / ignored / fixed
    # W7 反馈采集：false_positive（误报）/ confirmed（确认有效）/ fixed_by_user（已修复）
    feedback_reason: str | None = None
    # W7-5 误报原因标签（false_positive 时可选填，见 FEEDBACK_CAUSES）
    feedback_cause: str | None = None


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    ext: str
    doc_type: str
    status: str
    size_bytes: int
    created_at: datetime
