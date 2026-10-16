"""解析器插件注册表（P2-2 解析插件化）。

- 每个扩展名注册一个解析器，返回 ParseResult；新增格式只需实现 parse 并 @register_parser；
- 解析器不可自行写任务状态：需要闸门/失败时抛 ParserGate / ParserFail，
  由 parse_pipeline 统一落状态，保证状态机不分散。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ParseResult:
    plaintext: str
    page_count: int = 0
    table_count: int = 0
    used_ocr: bool = False
    warnings: list[dict] = field(default_factory=list)


class ParserGate(Exception):
    """解析器请求人工闸门（OCR 重试 / 解析失败处理等）。"""

    def __init__(self, reason: str, message: str, payload: dict | None = None):
        self.reason = reason
        self.message = message
        self.payload = payload or {}
        super().__init__(message)


class ParserFail(Exception):
    """解析器请求终态失败（无需人工介入）。"""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class ParserUnsupported(Exception):
    """格式无注册解析器。"""


PublishFn = Callable[[str, str], None]  # (stage, message) -> None
_PARSERS: dict[str, Callable] = {}


def register_parser(ext: str):
    """装饰器：注册扩展名解析器（ext 小写，可逗号分隔多个）。"""

    def deco(fn):
        for e in ext.split(","):
            _PARSERS[e.strip().lower()] = fn
        return fn

    return deco


def get_parser(ext: str):
    return _PARSERS.get((ext or "").lower())


# 导入子模块以完成注册（放末尾避免循环导入）
from app.services.parsers import docx_parser, pdf_parser, text_parser  # noqa: E402,F401
