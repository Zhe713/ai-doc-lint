"""工作台首页统计接口（W6 Day30）：文档数/批次/发现问题/规则包/向量化，全部真实数据。"""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.checkers.loader import RULES_DIR
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.document import CheckFinding, Document, TaskGroup
from app.models.embed import DocumentChunk
from app.models.user import User

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/stats")
def dashboard_stats(
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    docs = db.execute(
        select(func.count(Document.id)).where(Document.user_id == current.id)
    ).scalar_one()
    groups = db.execute(
        select(func.count(TaskGroup.id)).where(TaskGroup.user_id == current.id)
    ).scalar_one()
    findings_total = db.execute(
        select(func.count(CheckFinding.id)).where(
            CheckFinding.user_id == current.id)
    ).scalar_one()
    by_severity = {
        sev: db.execute(
            select(func.count(CheckFinding.id)).where(
                CheckFinding.user_id == current.id,
                CheckFinding.severity == sev)
        ).scalar_one()
        for sev in ("error", "warning", "info")
    }
    rule_packs = len(list(RULES_DIR.glob("*.yaml")))
    chunks = db.execute(
        select(func.count(DocumentChunk.id)).join(
            Document, Document.id == DocumentChunk.document_id
        ).where(Document.user_id == current.id)
    ).scalar_one()
    embedded_docs = db.execute(
        select(func.count(func.distinct(DocumentChunk.document_id))).join(
            Document, Document.id == DocumentChunk.document_id
        ).where(Document.user_id == current.id)
    ).scalar_one()
    return {
        "documents": docs,
        "groups": groups,
        "findings_total": findings_total,
        "findings_by_severity": by_severity,
        "rule_packs": rule_packs,
        "chunks": chunks,
        "embedded_docs": embedded_docs,
    }
