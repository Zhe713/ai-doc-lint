"""L3 Agent 只读工具：查 findings、取文档文本、文档内关键词检索。

全部只读、限定在当前会话绑定的文档内；写操作不在工具白名单中。
"""

from sqlalchemy.orm import Session

from app.db import storage
from app.models.document import Artifact, CheckFinding

WINDOW = 120
MAX_HITS = 5
TEXT_CHUNK = 4000

import re

# 条款标题（可含空格/全角空格）：第X条 / 第X章（条级优先）
_SECTION_RE = re.compile(r"(?m)^\s*第\s*([零一二两三四五六七八九十百\d]+)\s*条")
_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100}


def _ordinal_value(s: str) -> int | None:
    """第X条 的中文/数字序号 → int；无法解析返回 None。"""
    if s.isdigit():
        return int(s)
    total = 0
    num = 0
    for ch in s:
        if ch in _CN_DIGITS:
            num = _CN_DIGITS[ch]
        elif ch in _CN_UNITS:
            u = _CN_UNITS[ch]
            total += (num if num else 1) * u
            num = 0
        else:
            return None
    return total + num


def _find_section(text: str, ordinal_str: str):
    """按‘第X条’标题定位条款正文区间；找不到返回 None。"""
    want = _ordinal_value(ordinal_str)
    if want is None:
        return None
    starts: list[tuple[int, int]] = []
    for m in _SECTION_RE.finditer(text):
        v = _ordinal_value(m.group(1))
        if v is not None:
            starts.append((v, m.start()))
    if not starts:
        return None
    for i, (v, pos) in enumerate(starts):
        if v == want:
            end = starts[i + 1][1] if i + 1 < len(starts) else len(text)
            return pos, end
    return None


def _norm_text(text: str):
    """去空白；返回 (归一化串, 每字符对应原文位置)。"""
    parts: list[str] = []
    positions: list[int] = []
    for i, ch in enumerate(text):
        if ch.isspace():
            continue
        parts.append(ch)
        positions.append(i)
    return "".join(parts), positions


def get_findings(db: Session, document_id, *, severity: str | None = None,
                 status: str | None = None) -> list[dict]:
    q = db.query(CheckFinding).filter(CheckFinding.document_id == document_id)
    if severity:
        q = q.filter(CheckFinding.severity == severity)
    if status:
        q = q.filter(CheckFinding.status == status)
    rows = q.order_by(CheckFinding.id).all()
    return [
        {
            "id": str(f.id), "checker": f.checker, "rule_id": f.rule_id,
            "severity": f.severity, "message": f.message,
            "suggestion": f.suggestion, "status": f.status,
            "snippet": (f.location or {}).get("snippet"),
        }
        for f in rows
    ]


def _plaintext(db: Session, document_id) -> str | None:
    artifact = (
        db.query(Artifact)
        .filter(Artifact.document_id == document_id,
                Artifact.kind == "plaintext")
        .one_or_none()
    )
    if artifact is None:
        return None
    return storage.get_object_bytes(
        artifact.storage_key
    ).decode("utf-8", errors="replace")


def get_document_text(db: Session, document_id, *, start: int = 0,
                      length: int = TEXT_CHUNK) -> dict:
    text = _plaintext(db, document_id)
    if text is None:
        return {"found": False, "text": ""}
    start = max(0, int(start or 0))
    length = min(max(1, int(length or TEXT_CHUNK)), TEXT_CHUNK)
    return {
        "found": True, "start": start,
        "total_chars": len(text),
        "text": text[start:start + length],
    }


def search_in_document(db: Session, document_id, *, query: str) -> dict:
    text = _plaintext(db, document_id)
    if text is None:
        return {"found": False, "query": query, "matches": []}
    query = (query or "").strip()
    if not query:
        return {"found": False, "query": query, "matches": []}
    matches: list[dict] = []

    # 1) 精确子串匹配（原逻辑）
    start = 0
    while len(matches) < MAX_HITS:
        idx = text.find(query, start)
        if idx == -1:
            break
        matches.append({
            "position": idx,
            "context": text[max(0, idx - WINDOW):idx + len(query) + WINDOW],
        })
        start = idx + len(query)

    # 2) 条号条款定位：query 含“第X条”，返回该条正文整段（P1-4 条号召回）
    if not matches:
        m = re.search(r"第\s*([零一二两三四五六七八九十百\d]+)\s*条", query)
        if m:
            section = _find_section(text, m.group(1))
            if section:
                pos, end = section
                matches.append({
                    "position": pos,
                    "context": text[pos:min(end, pos + TEXT_CHUNK)],
                })

    # 3) 空格归一化兜底：去除所有空白后再匹配（兼容“第二条付款条件”对“第二条 付款条件”）
    if not matches:
        norm_text, norm_pos = _norm_text(text)
        norm_query = re.sub(r"\s+", "", query)
        nidx = norm_text.find(norm_query)
        if nidx != -1:
            idx = norm_pos[nidx]
            matches.append({
                "position": idx,
                "context": text[max(0, idx - WINDOW):idx + len(norm_query) + WINDOW],
            })

    return {"found": bool(matches), "query": query, "matches": matches}
