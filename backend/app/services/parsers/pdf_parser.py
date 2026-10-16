"""PDF 解析器：pdfium 文本层探测 → 密度评估 → docling 结构化 / OCR 兜底。

逻辑从 parse_pipeline 迁移而来（P2-2 插件化）：解析器只产出结果或抛
ParserGate / ParserFail，不直接写任务状态。
"""

from __future__ import annotations

import io
import logging
import os
import tempfile
import time

from app.core.config import settings
from app.services.parsers import (
    ParseResult,
    ParserFail,
    ParserGate,
    PublishFn,
    register_parser,
)

log = logging.getLogger("parser.pdf")

MIN_CHARS_PER_PAGE = 20
MIN_TOTAL_CHARS = 10
OCR_LOCK_PREFIX = "lock:ocr"
OCR_LOCK_TTL = 900  # 秒


def _pdfium_probe(data: bytes) -> tuple[str, int]:
    """零模型、零网络的 PDF 内嵌文本探测：pypdfium2 直接取文本层。"""
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


def _ocr_pdf(data: bytes) -> tuple[str, int]:
    """扫描件 PDF：逐页渲染后 RapidOCR（复用 PaddleOCR 权重，ONNX Runtime）。"""
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


def _run_ocr(data: bytes, publish: PublishFn) -> tuple[str, int]:
    """用户确认后的 OCR 执行；槽位等待超时抛 ParserFail。"""
    import redis

    publish("ocr", "OCR 识别中（RapidOCR）")
    r = redis.Redis.from_url(settings.valkey_url)
    slot = _wait_ocr_slot(r)
    if slot is None:
        raise ParserFail("ocr_timeout", "等待 OCR 资源超时")
    try:
        return _ocr_pdf(data)
    finally:
        r.delete(slot)


@register_parser("pdf")
def parse_pdf(data: bytes, *, attempts: int = 0, publish: PublishFn = None) -> ParseResult:
    publish = publish or (lambda stage, msg: None)

    # 第一层：pdfium 零成本探测文本层，扫描件不再惊动 docling/模型下载
    publish("probe", "PDF 文本层探测")
    try:
        probe_text, page_count = _pdfium_probe(data)
    except Exception as exc:  # noqa: BLE001
        raise ParserGate(
            "parse_failed",
            f"PDF 探测失败: {type(exc).__name__}: {exc}",
            {"ext": "pdf"},
        ) from exc

    if _low_density(probe_text, page_count):
        if attempts == 0:
            chars_per_page = len(probe_text) / max(page_count, 1)
            raise ParserGate(
                "ocr_required",
                "文档疑似扫描件/图片型 PDF，文本层内容过少",
                {"chars": len(probe_text), "pages": page_count,
                 "chars_per_page": round(chars_per_page, 1)},
            )
        plaintext, page_count = _run_ocr(data, publish)
        return ParseResult(plaintext=plaintext, page_count=page_count, used_ocr=True)

    # 文本健康：docling 提供结构化（表格/标题），失败则回退 pdfium 文本，离线可用
    publish("extract", "docling 结构化抽取")
    warnings: list[dict] = []
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
        warnings.append({
            "code": "docling_unavailable_fallback_pdfium",
            "reason": f"{type(exc).__name__}: {str(exc)[:200]}",
        })
        table_count = 0
    finally:
        os.unlink(tmp.name)

    return ParseResult(plaintext=plaintext, page_count=page_count,
                       table_count=table_count, warnings=warnings)
