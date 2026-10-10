"""格式规则包加载：读取 YAML 并做最小校验。

W3 只加载内置 format_default.yaml；W6 支持用户自定义路径覆盖。
"""

import functools
from pathlib import Path

import yaml

RULES_DIR = Path(__file__).parent / "rules"
DEFAULT_FORMAT_RULES = "format_default.yaml"
CLAUSE_PACKS = {
    "contract": "clause_contract.yaml",
}
FIELD_PACKS = {
    "contract": "fields_contract.yaml",
}
CROSS_PACKS = {
    "contract": "cross_contract.yaml",
}


class RuleConfigError(Exception):
    pass


@functools.lru_cache(maxsize=8)
def load_format_rules(name: str = DEFAULT_FORMAT_RULES) -> dict:
    path = RULES_DIR / name
    if not path.exists():
        raise RuleConfigError(f"格式规则包不存在: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1:
        raise RuleConfigError(f"格式规则包格式非法: {path}")
    for key in ("page", "font", "paragraph", "heading"):
        if not isinstance(data.get(key), dict):
            raise RuleConfigError(f"格式规则包缺少段落: {key}")
    return data


@functools.lru_cache(maxsize=8)
def load_clause_pack(doc_type: str) -> list[dict]:
    """按文档类型加载条款规则包；该类型无包时返回空列表（调用方据此 skip）。"""
    name = CLAUSE_PACKS.get(doc_type)
    if not name:
        return []
    path = RULES_DIR / name
    if not path.exists():
        raise RuleConfigError(f"条款规则包不存在: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1:
        raise RuleConfigError(f"条款规则包格式非法: {path}")
    clauses = data.get("clauses")
    if not isinstance(clauses, list) or not clauses:
        raise RuleConfigError(f"条款规则包没有 clauses: {path}")
    for clause in clauses:
        for key in ("id", "name", "strong", "weak"):
            if key not in clause:
                raise RuleConfigError(f"条款缺少字段 {key}: {clause}")
    return clauses


@functools.lru_cache(maxsize=8)
def load_field_pack(doc_type: str) -> list[dict]:
    """按文档类型加载字段抽取规则包；该类型无包时返回空列表。"""
    name = FIELD_PACKS.get(doc_type)
    if not name:
        return []
    path = RULES_DIR / name
    if not path.exists():
        raise RuleConfigError(f"字段规则包不存在: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1:
        raise RuleConfigError(f"字段规则包格式非法: {path}")
    fields = data.get("fields")
    if not isinstance(fields, list) or not fields:
        raise RuleConfigError(f"字段规则包没有 fields: {path}")
    for field in fields:
        for key in ("key", "label", "type", "patterns"):
            if key not in field:
                raise RuleConfigError(f"字段缺少 {key}: {field}")
    return fields


@functools.lru_cache(maxsize=8)
def load_cross_rules(doc_type: str) -> dict | None:
    """按文档类型加载交叉比对规则包；该类型无包时返回 None（调用方据此 skip）。"""
    name = CROSS_PACKS.get(doc_type)
    if not name:
        return None
    path = RULES_DIR / name
    if not path.exists():
        raise RuleConfigError(f"交叉比对规则包不存在: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1:
        raise RuleConfigError(f"交叉比对规则包格式非法: {path}")
    checks = data.get("checks")
    if not isinstance(checks, list) or not checks:
        raise RuleConfigError(f"交叉比对规则包没有 checks: {path}")
    for check in checks:
        for key in ("id", "name", "fields", "severity"):
            if key not in check:
                raise RuleConfigError(f"勾稽规则缺少 {key}: {check}")
    return data
