"""纯文本解析器：txt / md 直接 UTF-8 解码（非法字节替换），单页。"""

from __future__ import annotations

from app.services.parsers import ParseResult, PublishFn, register_parser


@register_parser("txt,md")
def parse_text(data: bytes, *, attempts: int = 0, publish: PublishFn = None) -> ParseResult:
    publish = publish or (lambda stage, msg: None)
    publish("extract", "纯文本直接解码")
    plaintext = data.decode("utf-8", errors="replace")
    return ParseResult(plaintext=plaintext, page_count=1)
