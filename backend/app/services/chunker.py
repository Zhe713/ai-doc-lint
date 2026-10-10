"""分块器（W6 Day27）：按段落把 plaintext 切成 ~500 字符、带重叠的块。

中文合同与英文协议通用：以换行分段，逐段合并到目标长度；
超长单段按固定步进硬切并保留重叠，避免条款被拦腰截断导致语义丢失。
"""

from __future__ import annotations

CHUNK_TARGET_CHARS = 500
CHUNK_OVERLAP_CHARS = 50
CHUNK_MAX_CHARS = 800


def _split_paragraphs(text: str) -> list[str]:
    """按换行切段，去掉空白段。"""
    return [p.strip() for p in text.split("\n") if p.strip()]


def _hard_split(para: str, target: int, overlap: int) -> list[str]:
    """超长单段：按 target 步长、overlap 重叠硬切。"""
    step = max(target - overlap, 1)
    return [para[i:i + target].strip() for i in range(0, len(para), step)
            if para[i:i + target].strip()]


def chunk_text(text: str, target: int = CHUNK_TARGET_CHARS,
               overlap: int = CHUNK_OVERLAP_CHARS) -> list[str]:
    """把文本切成带重叠的块；空文本返回空列表。"""
    text = (text or "").strip()
    if not text:
        return []
    paras = _split_paragraphs(text)
    chunks: list[str] = []
    current = ""
    for p in paras:
        if len(p) > CHUNK_MAX_CHARS:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_hard_split(p, target, overlap))
            continue
        if current and len(current) + len(p) + 1 > target:
            chunks.append(current)
            current = f"{current[-overlap:]}\n{p}" if overlap else p
        else:
            current = f"{current}\n{p}" if current else p
    if current.strip():
        chunks.append(current)
    # 去重并过滤纯空白
    seen: set[str] = set()
    out: list[str] = []
    for c in chunks:
        c = c.strip()
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out
