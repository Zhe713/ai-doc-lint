# -*- coding: utf-8 -*-
"""P2-3 规则包 JSON 数据化测试：JSON 校验、内置包 JSON 加载、schema 接口、DB 自定义 JSON 包优先。"""

import json

import pytest

from app.checkers.loader import (
    CLAUSE_PACKS,
    CROSS_PACKS,
    DEFAULT_FORMAT_RULES,
    FIELD_PACKS,
    _read_builtin,
    invalidate_pack_caches,
    load_clause_pack,
    load_cross_rules,
    load_field_pack,
    load_format_rules,
)
from app.checkers.ruleset_schema import all_ruleset_schemas, ruleset_schema
from app.checkers.validate import RuleConfigError, validate_pack


def test_validate_pack_accepts_json_clause():
    text = json.dumps({
        "version": 1,
        "doc_types": ["contract"],
        "clauses": [
            {"id": "c1", "name": "当事人", "required": True, "severity": "error",
             "strong": ["甲方"], "weak": []},
        ],
    }, ensure_ascii=False)
    data = validate_pack("clause", text)
    assert data["clauses"][0]["id"] == "c1"


def test_validate_pack_rejects_bad_json():
    with pytest.raises(RuleConfigError):
        validate_pack("clause", "{not json")


def test_validate_pack_rejects_missing_field_json():
    text = json.dumps({
        "version": 1,
        "clauses": [{"id": "c1", "name": "x"}],  # 缺 strong/weak
    })
    with pytest.raises(RuleConfigError):
        validate_pack("clause", text)


def test_validate_pack_accepts_yaml_legacy():
    text = "version: 1\nclauses:\n  - id: c1\n    name: x\n    strong: [a]\n    weak: []\n"
    data = validate_pack("clause", text)
    assert data["clauses"][0]["id"] == "c1"


def test_builtin_json_files_exist_and_valid():
    for name in (DEFAULT_FORMAT_RULES, CLAUSE_PACKS["contract"],
                 FIELD_PACKS["contract"], CROSS_PACKS["contract"]):
        raw = _read_builtin(name)  # 优先读 .json
        assert raw.lstrip().startswith("{"), f"{name} 应读取到 JSON"
        data = json.loads(raw)
        assert data["version"] == 1


def test_builtin_packs_load_from_json():
    fmt = load_format_rules()
    assert "page" in fmt and "font" in fmt
    clauses = load_clause_pack("contract")
    assert isinstance(clauses, list) and len(clauses) >= 5
    fields = load_field_pack("contract")
    assert isinstance(fields, list) and len(fields) >= 3
    cross = load_cross_rules("contract")
    assert cross is not None and "checks" in cross


def test_ruleset_schema_shape():
    for pt in ("format", "clause", "field", "cross"):
        s = ruleset_schema(pt)
        assert "label" in s and "fields" in s
        assert s["fields"], f"{pt} schema 应有字段定义"
        for f in s["fields"]:
            assert {"key", "label", "type", "required"} <= set(f.keys())
    schemas = all_ruleset_schemas()
    assert set(schemas.keys()) == {"format", "clause", "field", "cross"}


def test_unknown_schema_raises():
    with pytest.raises(ValueError):
        ruleset_schema("nope")


def test_custom_json_pack_takes_priority(monkeypatch):
    """DB 自定义 JSON 包优先于内置包（loader 覆盖路径）。"""
    from app.models.rules import RulePack
    from app.checkers import loader

    json_pack = json.dumps({
        "version": 1,
        "doc_types": ["contract"],
        "clauses": [
            {"id": "clause.custom", "name": "自定义必含条款", "required": True,
             "severity": "error", "strong": ["自定义条款关键词"], "weak": []},
        ],
    }, ensure_ascii=False)

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def query(self, *a, **k):
            return self

        def filter(self, *a, **k):
            return self

        def order_by(self, *a, **k):
            return self

        def first(self):
            return SimpleRow(json_pack)

        def close(self):
            pass

    class SimpleRow:
        def __init__(self, content):
            self.yaml_content = content

    from app.db.session import SessionLocal as RealSL
    monkeypatch.setattr(loader, "_SESSION_FACTORY", lambda: FakeSession())
    invalidate_pack_caches()
    try:
        clauses = load_clause_pack("contract")
        assert any(c["id"] == "clause.custom" for c in clauses)
    finally:
        monkeypatch.setattr(loader, "_SESSION_FACTORY", None)
        invalidate_pack_caches()
