"""解析流水线：MinIO 取原件 → 格式分支 → docling 抽取 → 置信度评估 → 闸门/OCR → 产物回写。

W2 边界：
- txt/md 快速通道直接解码；docx/pdf 走 docling；
- 文本密度过低（疑似扫描件）→ 挂起等用户 OCR 重试；
- 解析异常 → 挂起并返回错误，不浪费自动重试；
- 闸门三选一在 api 层完成；本流水线只产出 PARSED / AWAITING / FAILED。
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
from app.tasks.events import append_event

log = logging.getLogger("pipeline")

# 每页平均字符数低于该值视为疑似扫描件/低置信（短文档合法文本不应触发）
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


def _wait_ocr_slot(redis_client) -> str | None:
    """按 OCR_CONCURRENCY 个全局槽位抢锁；最多等 5 分钟。"""
    deadline = time.time() + 300
    while time.time() < deadline:
        for i in range(max(1, settings.ocr_concurrency)):
            key = f"{OCR_LOCK_PREFIX}:{i}"
            if redis_client.set(key, "1", nx=True, ex=OCR_LOCK_TTL):
                return key
        time.sleep(2)
    return None


def _ocr_pdf(data: bytes) -> tuple[str, int]:
    """扫描件 PDF：逐页渲染后 RapidOCR（复用 PaddleOCR 权重，ONNX Runtime）。"""
    import io

    import numpy as np
    import pypdfium2 as pdfium
    from rapidocr_onnxruntime import RapidOCR

    ocr = RapidOCR()
    pdf = pdfium.PdfDocument(io.BytesIO(data))
    pages_text: list[str] = []
    for page in pdf:
        image = page.render(scale=2.0).to_pil().convert("RGB")
        result, _ = ocr(np.array(image))
        if result:
            pages_text.append("\n".join(line[1] for line in result))
        else:
            pages_text.append("")
    return "\n\n".join(pages_text), len(pages_text)


def _pdfium_probe(data: bytes) -> tuple[str, int]:
    """零模型、零网络的 PDF 内嵌文本探测：pypdfium2 直接取文本层。"""
    import io

    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(io.BytesIO(data))
    pages: list[str] = []
    for page in pdf:
        tp = page.get_textpage()
        try:
            pages.append(tp.get_text_range() or "")
        finally:
            tp.close()
    return "\n\n".join(pages), len(pages)


def _low_density(text: str, page_count: int) -> bool:
    chars_per_page = len(text or "") / max(page_count, 1)
    return chars_per_page < MIN_CHARS_PER_PAGE or len(text or "") < MIN_TOTAL_CHARS


def _run_ocr(db: Session, task, data, ext):
    """用户确认后的 OCR 执行；返回 (plaintext, page_count) 或 None（已写终态）。"""
    import redis

    _publish_progress(db, task, "ocr", "OCR 识别中（RapidOCR）")
    r = redis.Redis.from_url(settings.valkey_url)
    slot = _wait_ocr_slot(r)
    if slot is None:
        _fail(db, task, "ocr_timeout", "等待 OCR 资源超时")
        return None
    try:
        if ext == "pdf":
            plaintext, page_count = _ocr_pdf(data)
        else:
            _fail(db, task, "ocr_unsupported", "docx 扫描件请另存为 PDF 后重试 OCR")
            return None
    finally:
        r.delete(slot)
    return plaintext, page_count


def run_parse_pipeline(db: Session, task: DocumentTask, document) -> None:
    from app.db.session import SessionLocal  # noqa: F401  保留以便扩展

    _publish_progress(db, task, "download", "从对象存储读取原件")
    try:
        data = storage.get_object_bytes(document.storage_key)
    except Exception as exc:  # noqa: BLE001
        _fail(db, task, "object_not_found", f"读取原件失败: {exc}")
        return

    ext = (document.ext or "").lower()
    plaintext = ""
    page_count = 0
    table_count = 0
    used_ocr = False
    fallback_warnings: list[dict] = []

    try:
        if ext in ("txt", "md"):
            _publish_progress(db, task, "extract", "纯文本直接解码")
            plaintext = data.decode("utf-8", errors="replace")
            page_count = 1
        elif ext == "pdf":
            # 第一层：pdfium 零成本探测文本层，扫描件不再惊动 docling/模型下载
            _publish_progress(db, task, "probe", "PDF 文本层探测")
            try:
                probe_text, page_count = _pdfium_probe(data)
            except Exception as exc:  # noqa: BLE001
                _gate(
                    db, task, GATE_PARSE_FAILED,
                    f"PDF 探测失败: {type(exc).__name__}: {exc}", {"ext": ext},
                )
                return

            if _low_density(probe_text, page_count):
                if task.attempts == 0:
                    chars_per_page = len(probe_text) / max(page_count, 1)
                    _gate(
                        db, task, GATE_OCR_REQUIRED,
                        "文档疑似扫描件/图片型 PDF，文本层内容过少",
                        {"chars": len(probe_text), "pages": page_count,
                         "chars_per_page": round(chars_per_page, 1)},
                    )
                    return
                ocr_out = _run_ocr(db, task, data, ext)
                if ocr_out is None:
                    return
                plaintext, page_count = ocr_out
                used_ocr = True
            else:
                # 文本健康：docling 提供结构化（表格/标题），失败则回退 pdfium 文本，离线可用
                _publish_progress(db, task, "extract", "docling 结构化抽取")

                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
                try:
                    tmp.write(data)
                    tmp.close()
                    from docling.document_converter import DocumentConverter

                    converter = DocumentConverter()
                    result = converter.convert(tmp.name)
                    plaintext = result.document.export_to_text()
                    page_count = len(result.pages) if getattr(result, "pages", None) else (len(result.document.pages) or page_count)
                    table_count = len(result.document.tables or [])
                except Exception as exc:  # noqa: BLE001
                    log.warning("docling unavailable, fallback to pdfium: %s", exc)
                    plaintext = probe_text
                    fallback_warnings.append({
                        "code": "docling_unavailable_fallback_pdfium",
                        "reason": f"{type(exc).__name__}: {str(exc)[:200]}",
                    })
                finally:
                    os.unlink(tmp.name)
        elif ext == "docx":
            _publish_progress(db, task, "extract", "docling 抽取（docx）")
            from docling.document_converter import DocumentConverter

            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".docx")
            try:
                tmp.write(data)
                tmp.close()
                converter = DocumentConverter()
                result = converter.convert(tmp.name)
                plaintext = result.document.export_to_text()
                page_count = 1
                table_count = len(result.document.tables or [])
            finally:
                os.unlink(tmp.name)

            if _low_density(plaintext, page_count) and task.attempts == 0:
                _gate(
                    db, task, GATE_OCR_REQUIRED,
                    "docx 文本抽取量过低，可能含图片扫描内容",
                    {"chars": len(plaintext)},
                )
                return
            if _low_density(plaintext, page_count):
                _fail(db, task, "ocr_unsupported", "docx 扫描件请另存为 PDF 后重试 OCR")
                return
        else:
            _gate(
                db, task, GATE_UNSUPPORTED,
                f"不支持的格式 .{ext}", {"ext": ext},
            )
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

    stats = {
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

    # parse 成功后自动创建 review 任务（Day14 起具体检查项由意图路由决定）
    from app.services.review_service import create_review_task

    create_review_task(db, document)
