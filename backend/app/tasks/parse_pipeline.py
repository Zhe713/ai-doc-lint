"""解析流水线：MinIO 取原件 → 解析器插件（按扩展名注册）→ 置信度闸门 → 产物回写。

W2 边界（由插件内部分层保证）：
- txt/md 快速通道直接解码；docx/pdf 走 docling；
- 文本密度过低（疑似扫描件）→ 挂起等用户 OCR 重试；
- 解析异常 → 挂起并返回错误，不浪费自动重试；
- 闸门三选一在 api 层完成；本流水线只产出 PARSED / AWAITING / FAILED。
P2-2：解析器已插件化（app/services/parsers），状态落位仍统一在本流水线。
"""

import logging
import os
import tempfile
import time

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import storage
from app.models.document import (
    ART_NORMALIZED_JSON,
    ART_PLAINTEXT,
    GATE_LOW_CONFIDENCE,
    GATE_OCR_REQUIRED,
    GATE_PARSE_FAILED,
    GATE_UNSUPPORTED,
    STATUS_AWAITING,
    STATUS_FAILED,
    STATUS_PARSED,
    Artifact,
    DocumentTask,
)
from app.services import task_state
from app.services.parsers import (
    ParserFail,
    ParserGate,
    get_parser,
)
from app.tasks.events import append_event

log = logging.getLogger("pipeline")

MIN_CHARS_PER_PAGE = 20
MIN_TOTAL_CHARS = 10
OCR_LOCK_PREFIX = "lock:ocr"
OCR_LOCK_TTL = 900  # 秒


def _publish_progress(db: Session, task: DocumentTask, stage: str, message: str) -> None:
    append_event(db, task, "stage_progress", stage=stage, message=message)
    db.commit()


def _gate(db: Session, task: DocumentTask, reason: str, message: str, payload: dict) -> None:
    task_state.change_status(
        db, task, STATUS_AWAITING,
        event_type="gate_open", stage="gate",
        message=message,
        fields={"gate_reason": reason, "gate_payload": payload},
    )


def _fail(db: Session, task: DocumentTask, code: str, message: str) -> None:
    task_state.change_status(
        db, task, STATUS_FAILED,
        event_type="task_failed", stage="error", message=message,
        fields={"error_code": code, "error_message": message[:1000]},
    )


def _low_density(text: str, page_count: int) -> bool:
    chars_per_page = len(text or "") / max(page_count, 1)
    return chars_per_page < MIN_CHARS_PER_PAGE or len(text or "") < MIN_TOTAL_CHARS


def run_parse_pipeline(db: Session, task: DocumentTask, document) -> None:
    from app.db.session import SessionLocal  # noqa: F401  保留以便扩展

    _publish_progress(db, task, "download", "从对象存储读取原件")
    try:
        data = storage.get_object_bytes(document.storage_key)
    except Exception as exc:  # noqa: BLE001
        _fail(db, task, "object_not_found", f"读取原件失败: {exc}")
        return

    ext = (document.ext or "").lower()
    parser = get_parser(ext)
    if parser is None:
        _gate(
            db, task, GATE_UNSUPPORTED,
            f"不支持的格式 .{ext}", {"ext": ext},
        )
        return

    plaintext = ""
    page_count = 0
    table_count = 0
    used_ocr = False
    fallback_warnings: list[dict] = []

    try:
        result = parser(
            data,
            attempts=getattr(task, "attempts", 0),
            publish=lambda stage, msg: _publish_progress(db, task, stage, msg),
        )
        plaintext = result.plaintext
        page_count = result.page_count
        table_count = result.table_count
        used_ocr = result.used_ocr
        fallback_warnings = result.warnings
    except ParserGate as g:
        _gate(db, task, g.reason, g.message, g.payload)
        return
    except ParserFail as f:
        _fail(db, task, f.code, f.message)
        return
    except Exception as exc:  # noqa: BLE001
        log.exception("parse failed for task %s", task.id)
        _gate(db, task, GATE_PARSE_FAILED, f"解析失败: {type(exc).__name__}: {exc}", {"ext": ext})
        return

    char_count = len(plaintext or "")
    if char_count == 0 and not used_ocr:
        _gate(db, task, GATE_LOW_CONFIDENCE, "未抽取到任何文本", {"ext": ext})
        return

    # 产物回写
    _publish_progress(db, task, "normalize", "生成标准化产物")
    plaintext_key = f"artifacts/{task.document_id}/plaintext.txt"
    normalized_key = f"artifacts/{task.document_id}/normalized.json"
    import json

    storage.put_object(plaintext_key, (plaintext or "").encode("utf-8"), content_type="text/plain")
    normalized = {
        "ext": ext,
        "page_count": page_count,
        "char_count": char_count,
        "table_count": table_count,
        "ocr_used": used_ocr,
        "text": plaintext or "",
    }
    storage.put_object(normalized_key, json.dumps(normalized, ensure_ascii=False).encode("utf-8"), content_type="application/json")

    db.add(Artifact(document_id=task.document_id, task_id=task.id, kind=ART_PLAINTEXT, storage_key=plaintext_key))
    db.add(Artifact(document_id=task.document_id, task_id=task.id, kind=ART_NORMALIZED_JSON, storage_key=normalized_key))

    # 合并保留受理阶段写入的路由信息（checks/doc_type/route_*），不能整体覆盖
    stats = {
        **(task.stats or {}),
        "page_count": page_count,
        "char_count": char_count,
        "table_count": table_count,
        "ocr_used": used_ocr,
        "chars_per_page": round(char_count / max(page_count, 1), 1),
    }
    final_fields = {
        "stats": stats,
        "result_refs": {"plaintext": plaintext_key, "normalized": normalized_key},
    }
    if fallback_warnings:
        final_fields["warnings"] = list(task.warnings or []) + fallback_warnings
    task_state.change_status(
        db, task, STATUS_PARSED,
        event_type="task_succeeded", stage="done",
        message="解析完成",
        fields=final_fields,
    )

    # parse 成功后自动创建 review 任务；检查项/文档类型来自上传时的意图路由
    from app.services.review_service import create_review_task

    route_opts = task.stats or {}
    create_review_task(
        db, document,
        checks=route_opts.get("checks"),
        doc_type_hint=route_opts.get("doc_type"),
    )

    # W6：解析成功后自动向量化（本地 bge 模型，0 token；失败不影响已入库产物）
    try:
        from app.tasks.embed import create_embed_task

        create_embed_task(db, document)
    except Exception as exc:  # noqa: BLE001
        log.warning("create_embed_task failed, skip: %s", exc)
        db.rollback()
