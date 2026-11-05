"""核心检查器与解释器/工具的单元测试（补齐 0% 覆盖的纯逻辑模块）。

覆盖四块此前只在 Celery worker 进程里执行、测试进程从未直接触达的代码：
1. ruleset_explain：规则包 → 人话解释（rule_id / basis / counts）；
2. chat.tools：L3 只读工具（条号定位、空白归一化、原文区间、findings 查询）；
3. typo_checker 纯函数：候选归一化、整句上下文、LLM 输出解析、白名单区间；
4. format_checker 标题跳级判定。
"""

import json
import uuid
from types import SimpleNamespace

import pytest

from app.chat import tools as chat_tools
from app.checkers import ruleset_explain
from app.checkers import typo_checker as typo_mod
from app.checkers.format_checker import FormatChecker
from app.checkers.typo_checker import TypoChecker
from conftest import TestSessionLocal
from tests.test_findings_api import _upload_doc, _user_id


# ---------------- ruleset_explain ----------------


def _format_content() -> dict:
    return {
        "page": {
            "size": {"expected_mm": [210, 297], "tolerance_mm": 3, "severity": "warning"},
            "margin_cm": {"top": [2.5, 3.0], "bottom": 2.5, "severity": "info"},
        },
        "font": {"body_allow": ["仿宋", "宋体"], "body_size_pt": [10.5, 16], "severity": "warning"},
        "paragraph": {"first_line_indent_chars": 2, "unindented_ratio": 0.1, "min_chars": 10},
        "heading": {"enabled": True, "severity": "warning"},
    }


def test_explain_format_pack():
    result = ruleset_explain.explain_pack("format", _format_content())
    assert result["title"] == "格式规则"
    assert result["total"] == len(result["items"]) == 6
    ids = {it["rule_id"] for it in result["items"]}
    assert ids == {
        "format.page.size", "format.page.margin", "format.font.body",
        "format.font.size", "format.paragraph.indent", "format.heading.sequence",
    }
    size = next(it for it in result["items"] if it["rule_id"] == "format.page.size")
    assert "A4" in size["detail"] and "3 毫米" in size["detail"]
    assert size["severity_label"] == "警告"
    assert result["counts"]["rule"] == 6


def test_explain_clause_pack_three_bases():
    content = {"clauses": [
        {"id": "c1", "name": "违约责任", "strong": ["违约"], "weak": ["赔偿"], "severity": "error"},
        {"id": "c2", "name": "争议解决", "strong": [], "required": True},
        {"id": "c3", "name": "通知送达", "required": False},
    ]}
    result = ruleset_explain.explain_pack("clause", content)
    by_id = {it["rule_id"]: it for it in result["items"]}
    assert by_id["c1"]["basis"] == "hybrid" and "「违约」" in by_id["c1"]["detail"]
    assert by_id["c2"]["basis"] == "llm"  # 无弱信号 → 全靠大模型语义确认
    assert by_id["c3"]["basis"] == "rule"  # 可选条款
    assert result["counts"] == {"rule": 1, "hybrid": 1, "llm": 1}


def test_explain_field_and_cross_packs():
    field = ruleset_explain.explain_pack("field", {"fields": [
        {"key": "amount", "label": "合同金额", "type": "money", "patterns": ["人民币", "¥"]},
    ]})
    assert field["items"][0]["rule_id"] == "amount"
    assert "「人民币」" in field["items"][0]["detail"]

    cross = ruleset_explain.explain_pack("cross", {"checks": [
        {"id": "x1", "name": "总价勾稽", "fields": ["amount", "amount_cn"],
         "description": "大小写金额应一致。", "severity": "error"},
    ]})
    item = cross["items"][0]
    assert item["rule_id"] == "x1"
    assert "「amount」 与 「amount_cn」" in item["detail"]
    assert "大小写金额应一致" in item["detail"]


def test_explain_pack_edge_cases():
    with pytest.raises(ValueError):
        ruleset_explain.explain_pack("unknown", {})
    # content 不是 dict（历史上内置包解释曾因此整页空白）→ 不崩，返回空
    empty = ruleset_explain.explain_pack("format", "not-a-dict")
    assert empty["total"] == 0
    # _paper_name 对非法输入安全
    assert ruleset_explain._paper_name(None) == "未设置"
    assert ruleset_explain._paper_name([1, "x"]).startswith("1×")
    assert ruleset_explain._range_text(None, "磅") == "未设置"
    assert ruleset_explain._get({"a": {"b": 1}}, "a.b") == 1
    assert ruleset_explain._get({"a": 1}, "a.b.c") is None


# ---------------- chat.tools ----------------


def test_ordinal_and_section_helpers():
    assert chat_tools._ordinal_value("3") == 3
    assert chat_tools._ordinal_value("十") == 10
    assert chat_tools._ordinal_value("十二") == 12
    assert chat_tools._ordinal_value("二十三") == 23
    assert chat_tools._ordinal_value("bad") is None

    text = "第一条 总则\n甲方乙方。\n第三条 付款\n货款两清。"
    sec = chat_tools._find_section(text, "一")
    assert sec and text[sec[0]:sec[1]].startswith("第一条")
    third = chat_tools._find_section(text, "三")
    assert text[third[0]:third[1]].startswith("第三条")
    assert chat_tools._find_section(text, "二") is None
    assert chat_tools._find_section(text, "xyz") is None

    # 「第二条␣␣付款」两个空格：归一化后「付」对应原文位置 5
    norm, pos = chat_tools._norm_text("第二条  付款")
    assert norm == "第二条付款"
    assert pos[3] == 5


def test_get_document_text_and_search(client, monkeypatch):
    monkeypatch.setattr("app.api.documents.enqueue_parse", lambda task_id: None)
    from app.models.document import Artifact

    text = "第一条 总则\n本合同一式两份。\n第二条 违约责任\n任何一方违约应赔偿损失。"
    monkeypatch.setattr(
        "app.db.storage.get_object_bytes", lambda key: text.encode("utf-8")
    )
    headers = _upload_headers(client)
    doc_id = _upload_doc(client, headers)

    db = TestSessionLocal()
    try:
        db.add(Artifact(document_id=uuid.UUID(doc_id), kind="plaintext",
                        storage_key=f"test/{doc_id}.txt"))
        db.commit()

        # get_document_text：区间读取
        r = chat_tools.get_document_text(db, doc_id, start=0, length=10)
        assert r["found"] and r["total_chars"] == len(text)
        assert r["text"] == text[:10]

        # 精确子串
        r = chat_tools.search_in_document(db, doc_id, query="违约")
        assert r["found"] and "赔偿损失" in r["matches"][0]["context"]

        # 条号定位：query 本身没出现在正文，但含「第二条」
        r = chat_tools.search_in_document(db, doc_id, query="第二条的义务有哪些")
        assert r["found"] and r["matches"][0]["context"].startswith("第二条")

        # 空白归一化兜底：正文里「违约责任」前有空格，query 里没有
        r = chat_tools.search_in_document(db, doc_id, query="违约责任任何一方")
        assert r["found"]

        # 全都未命中 → 语义兜底（无向量数据时静默降级为未找到）
        r = chat_tools.search_in_document(db, doc_id, query="绝不存在的词xyz")
        assert r["found"] is False and r["matches"] == []

        # 空 query / 无原文文档
        assert chat_tools.search_in_document(db, doc_id, query="  ")["found"] is False
    finally:
        db.close()


def _upload_headers(client):
    from tests.test_intake import _auth
    return _auth(client, "unit_chat_tools")


def test_get_findings_filters(client, monkeypatch):
    from app.models.document import CheckFinding
    from tests.test_intake import _auth

    monkeypatch.setattr("app.api.documents.enqueue_parse", lambda task_id: None)
    headers = _auth(client, "unit_findings")  # 建用户 + 真实文档，满足外键
    uid = _user_id("unit_findings")
    doc_id = _upload_doc(client, headers)
    db = TestSessionLocal()
    try:
        db.add(CheckFinding(document_id=uuid.UUID(doc_id), user_id=uid,
                            checker="format", rule_id="f1",
                            severity="error", message="甲", status="open"))
        db.add(CheckFinding(document_id=uuid.UUID(doc_id), user_id=uid,
                            checker="typo", rule_id="t1",
                            severity="warning", message="乙", status="fixed",
                            location={"snippet": "原文片段"}))
        db.commit()
        rows = chat_tools.get_findings(db, doc_id)
        assert len(rows) == 2 and rows[0]["message"] == "甲"
        rows = chat_tools.get_findings(db, doc_id, status="open")
        assert len(rows) == 1 and rows[0]["checker"] == "format"
        rows = chat_tools.get_findings(db, doc_id, severity="warning")
        assert rows[0]["snippet"] == "原文片段"
    finally:
        db.close()


# ---------------- typo_checker 纯函数 ----------------


def test_normalize_errors_variants():
    # 4 元组
    assert typo_mod._normalize_errors(
        {"errors": [("签定", "签订", 3, 5)]}) == [("签定", "签订", 3, 5)]
    # 3 元组 → end 自动补 len(wrong)
    assert typo_mod._normalize_errors(
        ([], [("签定", "签订", 3)])) == [("签定", "签订", 3, 5)]
    # 非法形状被跳过 / 完全异常的输入
    assert typo_mod._normalize_errors(([], [("只有", "两个")])) == []
    assert typo_mod._normalize_errors("garbage") == []


def test_sentence_context_and_parse():
    text = "双方签定本合同。本合同一式两份，具有同等法律效力；未尽事宜另行协商。"
    ctx = TypoChecker._sentence_context(text, 2, 4)  # 「签定」所在句
    assert ctx == "双方签定本合同。"
    # cap 限制：左右各取 cap 字
    long_text = "前" * 100 + "目标词" + "后" * 100
    ctx2 = TypoChecker._sentence_context(long_text, 100, 103, cap=10)
    assert len(ctx2) == 23  # 10 前 + 3 词 + 10 后

    # _parse：合法 JSON
    ok = TypoChecker._parse(json.dumps(
        {"verdicts": [{"index": 0, "is_error": True, "correction": "签订"}]}), 1)
    assert ok and ok[0]["is_error"] is True
    # 非法 / 字段类型错误
    assert TypoChecker._parse("not json", 1) is None
    assert TypoChecker._parse(json.dumps({"verdicts": [{"index": "0", "is_error": True}]}), 1) is None


def test_protected_spans_and_overlaps():
    checker = object.__new__(TypoChecker)  # 只测实例纯方法，不跑 __init__
    text = "甲方应支付款项，甲方履约。"
    spans = checker._protected_spans(text)
    assert spans, "白名单词（如「甲方」）应命中保护区间"
    # 「甲方」区间 (0,2) 与 (8,10)
    assert checker._overlaps(("甲方", "甲方", 1, 3), spans)
    assert checker._overlaps(("甲方", "甲方", 7, 9), spans)
    assert not checker._overlaps(("签定", "签订", 4, 6), spans)


# ---------------- format_checker 标题跳级 ----------------


class _FakeCollector:
    def __init__(self):
        self.added = []

    def add(self, **kwargs):
        self.added.append(kwargs)


def _heading_checker() -> FormatChecker:
    checker = object.__new__(FormatChecker)  # 跳过 __init__，只测纯方法
    checker.checker = "format"
    checker.rules = {"heading": {"severity": "warning"}}
    checker.collector = _FakeCollector()
    return checker


def test_heading_sequence_detects_skip():
    fc = _heading_checker()
    fc._check_heading_sequence(
        ["一、总则", "1. 具体条款", "正文不属于标题"], location_kind="paragraph"
    )
    assert len(fc.collector.added) == 1
    finding = fc.collector.added[0]
    assert finding["rule_id"] == "format.heading.sequence"
    assert "缺少" in finding["message"] and "（一）" in finding["message"]
    assert finding["location"]["paragraph_index"] == 1


def test_heading_sequence_no_skip_no_finding():
    fc = _heading_checker()
    fc._check_heading_sequence(
        ["一、总则", "（一）背景", "1. 范围", "（1）细化"], location_kind="line"
    )
    assert fc.collector.added == []
