"""DOCX 解析器：docling 抽取文本与表格；低密度走 OCR 闸门（由 pipeline 落状态）。"""

from __future__ import annotations

import os
import tempfile

from app.services.parsers import (
    ParseResult,
    ParserFail,
    ParserGate,
    PublishFn,
    register_parser,
)

MIN_CHARS_PER_PAGE = 20
MIN_TOTAL_CHARS = 10


def _low_density(text: str) -> bool:
    return len(text or "") < MIN_TOTAL_CHARS


@register_parser("docx")
def parse_docx(data: bytes, *, attempts: int = 0, publish: PublishFn = None) -> ParseResult:
    publish = publish or (lambda stage, msg: None)
    publish("extract", "docling 抽取（docx）")

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

    if _low_density(plaintext):
        if attempts == 0:
            raise ParserGate(
                "ocr_required",
                "docx 文本抽取量过低，可能含图片扫描内容",
                {"chars": len(plaintext)},
            )
        raise ParserFail("ocr_unsupported", "docx 扫描件请另存为 PDF 后重试 OCR")

    return ParseResult(plaintext=plaintext, page_count=page_count,
                       table_count=table_count)
