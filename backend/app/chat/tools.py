"""L3 Agent 只读工具：查 findings、取文档文本、文档内关键词检索。

全部只读、限定在当前会话绑定的文档内；写操作不在工具白名单中。
"""

from sqlalchemy.orm import Session

from app.db import storage
from app.models.document import Artifact, CheckFinding

WINDOW = 120
MAX_HITS = 5
TEXT_CHUNK = 4000


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
    matches: list[dict] = []
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
    return {"found": bool(matches), "query": query, "matches": matches}
