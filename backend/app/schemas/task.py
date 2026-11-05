"""任务/文档相关响应模型。"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator


class UploadedTaskOut(BaseModel):
    task_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    status: str


class DuplicateItemOut(BaseModel):
    """被 sha256 去重跳过的文件（同用户已有同内容文档）。"""

    filename: str
    document_id: str | None = None
    task_id: str | None = None
    created_at: str | None = None
    reason: str = "already_uploaded"  # already_uploaded / same_batch


class UploadOut(BaseModel):
    group_id: uuid.UUID
    total: int
    tasks: list[UploadedTaskOut]
    # 去重跳过的文件；全部重复时接口返回 409，不会走到这里
    duplicates: list[DuplicateItemOut] = []


class TaskGroupOut(BaseModel):
    id: uuid.UUID
    total: int
    pending: int
    running: int
    succeeded: int
    awaiting: int
    failed: int
    cancelled: int
    finished_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}

    # 历史脏计数防御：任务并发/中断场景下冗余计数可能被减成负数，UI 不应展示 -1
    @field_validator("pending", "running", "succeeded", "awaiting", "failed", "cancelled")
    @classmethod
    def _clamp_non_negative(cls, v: int) -> int:
        return max(v, 0)


class TaskEventOut(BaseModel):
    event_type: str
    stage: str | None
    message: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TaskOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    group_id: uuid.UUID | None
    filename: str
    task_type: str
    status: str
    gate_reason: str | None
    gate_payload: dict | None
    warnings: list | None
    stats: dict | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class TaskDetailOut(TaskOut):
    events: list[TaskEventOut]


class DecisionIn(BaseModel):
    action: Literal["retry_ocr", "continue_with_warnings", "cancel"]
