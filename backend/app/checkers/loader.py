"""格式规则包加载：读取 YAML 并做最小校验。

W3 只加载内置 format_default.yaml；W6 支持用户自定义路径覆盖。
"""

import functools
from pathlib import Path

import yaml

RULES_DIR = Path(__file__).parent / "rules"
DEFAULT_FORMAT_RULES = "format_default.yaml"


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
