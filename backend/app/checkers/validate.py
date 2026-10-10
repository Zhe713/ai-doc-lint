"""规则包 YAML 校验纯函数（W6 Day26）：loader 与上传 API 共用。

把 loader 中分散的校验逻辑收敛为单一入口 validate_pack_yaml：
- 上传自定义包时先校验，非法包直接拒绝入库；
- loader 从 DB 读自定义包时同样走该校验，保证内容质量一致。
"""

from __future__ import annotations

from pathlib import Path

import yaml

RULES_DIR = Path(__file__).parent / "rules"

PACK_TYPES = ("format", "clause", "field", "cross")


class RuleConfigError(Exception):
    pass


def validate_pack_yaml(pack_type: str, text: str) -> dict:
    """校验规则包 YAML；合法返回解析后的 dict，非法抛 RuleConfigError。"""
    if pack_type not in PACK_TYPES:
        raise RuleConfigError(f"未知规则包类型: {pack_type}")
    try:
        data = yaml.safe_load(text or "")
    except yaml.YAMLError as exc:
        raise RuleConfigError(f"YAML 解析失败: {exc}") from exc
    if not isinstance(data, dict) or data.get("version") != 1:
        raise RuleConfigError("规则包格式非法：必须是 version=1 的 YAML 对象")

    if pack_type == "format":
        for key in ("page", "font", "paragraph", "heading"):
            if not isinstance(data.get(key), dict):
                raise RuleConfigError(f"格式规则包缺少段落: {key}")
    elif pack_type == "clause":
        clauses = data.get("clauses")
        if not isinstance(clauses, list) or not clauses:
            raise RuleConfigError("条款规则包没有 clauses 列表")
        for clause in clauses:
            for key in ("id", "name", "strong", "weak"):
                if key not in clause:
                    raise RuleConfigError(f"条款缺少字段 {key}: {clause}")
    elif pack_type == "field":
        fields = data.get("fields")
        if not isinstance(fields, list) or not fields:
            raise RuleConfigError("字段规则包没有 fields 列表")
        for field in fields:
            for key in ("key", "label", "type", "patterns"):
                if key not in field:
                    raise RuleConfigError(f"字段缺少 {key}: {field}")
    elif pack_type == "cross":
        checks = data.get("checks")
        if not isinstance(checks, list) or not checks:
            raise RuleConfigError("勾稽规则包没有 checks 列表")
        for check in checks:
            for key in ("id", "name", "fields", "severity"):
                if key not in check:
                    raise RuleConfigError(f"勾稽规则缺少 {key}: {check}")
    return data


def pack_sub_payload(pack_type: str, data: dict):
    """从校验后的 dict 提取各类加载器实际使用的子结构。

    loader 内置文件路径也复用此函数，保证 DB 自定义包与内置包结构一致。
    """
    if pack_type == "format":
        return data
    if pack_type == "clause":
        return data.get("clauses") or []
    if pack_type == "field":
        return data.get("fields") or []
    if pack_type == "cross":
        return data
    raise RuleConfigError(f"未知规则包类型: {pack_type}")
