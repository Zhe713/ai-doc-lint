# -*- coding: utf-8 -*-
"""P2-2 解析插件化测试：注册表、纯文本解析、PDF 闸门/回退、DOCX 异常外抛。"""

import pytest

from app.services.parsers import ParserGate, get_parser
from app.services.parsers import pdf_parser


def test_registry_covers_builtin_exts():
    for ext in ("pdf", "docx", "txt", "md"):
        assert get_parser(ext) is not None, f"缺少 {ext} 解析器"
    assert get_parser("xls") is None
    assert get_parser("") is None


def test_text_parser_decodes_utf8():
    from app.services.parsers import text_parser

    r = text_parser.parse_text("甲方：北京某公司。乙方：上海某公司。".encode("utf-8"))
    assert "甲方" in r.plaintext
    assert r.page_count == 1


def test_text_parser_replaces_invalid_bytes():
    from app.services.parsers import text_parser

    r = text_parser.parse_text(b"\xff\xfe\x00abc")
    assert "abc" in r.plaintext


def test_pdf_invalid_bytes_gate_parse_failed():
    with pytest.raises(ParserGate) as ei:
        pdf_parser.parse_pdf(b"not a pdf at all")
    assert ei.value.reason == "parse_failed"


def test_pdf_low_density_gate_ocr_required(monkeypatch):
    # 探测返回空文本（模拟纯扫描件），首次尝试应开 OCR 闸门，不触发 OCR
    monkeypatch.setattr(pdf_parser, "_pdfium_probe", lambda data: ("", 3))
    with pytest.raises(ParserGate) as ei:
        pdf_parser.parse_pdf(b"x", attempts=0)
    assert ei.value.reason == "ocr_required"
    assert ei.value.payload["pages"] == 3


def test_pdf_low_density_with_attempts_runs_ocr(monkeypatch):
    monkeypatch.setattr(pdf_parser, "_pdfium_probe", lambda data: ("", 2))
    monkeypatch.setattr(pdf_parser, "_run_ocr", lambda data, publish: ("扫描识别结果文本", 2))
    r = pdf_parser.parse_pdf(b"x", attempts=1)
    assert r.used_ocr is True
    assert "扫描" in r.plaintext


def test_pdf_healthy_docling_struct(monkeypatch):
    monkeypatch.setattr(pdf_parser, "_pdfium_probe", lambda data: ("合同正文足够长..." * 10, 1))

    class FakeTables:
        pass

    class FakeDoc:
        tables = [FakeTables()]

        def export_to_text(self):
            return "合同正文足够长..." * 10

    class FakeResult:
        pages = [1]
        document = FakeDoc()

    class FakeConverter:
        def __init__(self):
            pass

        def convert(self, path):
            return FakeResult()

    import docling.document_converter as dc
    monkeypatch.setattr(dc, "DocumentConverter", FakeConverter)
    r = pdf_parser.parse_pdf(b"x")
    assert r.table_count == 1
    assert "合同正文" in r.plaintext


def test_docx_converter_error_propagates(monkeypatch):
    # docling 离线/异常时异常外抛，由 pipeline 落 parse_failed 闸门
    import docling.document_converter as dc

    class BoomConverter:
        def __init__(self):
            pass

        def convert(self, path):
            raise RuntimeError("hub offline")

    monkeypatch.setattr(dc, "DocumentConverter", BoomConverter)
    from app.services.parsers import docx_parser

    with pytest.raises(RuntimeError):
        docx_parser.parse_docx(b"PK\x03\x04fake-docx")


def test_get_parser_after_import_registered():
    # 包导入子模块后注册表非空（防空注册回归）
    assert len(list(get_parser(e) for e in ("pdf", "docx", "txt", "md"))) == 4
