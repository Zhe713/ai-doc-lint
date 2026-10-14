"""annotate（批注版生成）任务（W4 Day18）。

纯确定性、不调用 LLM：
- docx：python-docx 1.2 原生 add_comment，把问题写成真 Word 批注；
  snippet 在正文/表格段落中匹配不到的问题，汇总到文末「问题清单」；
- pdf/txt/md：无法回写批注，生成一份「问题清单」docx。

产物入 MinIO（kind=annotated），result_refs.annotated 指向存储键。
"""

import io
import logging
import uuid

from docx import Document as DocxDocument
from docx.enum.text import WD_ALIGN_PARAGRAPH

from app.db import storage
from app.db.session import SessionLocal
from sqlalchemy.orm import Session
from app.models.document import (
    ART_ANNOTATED,
    STATUS_PENDING,
    Artifact,
    CheckFinding,
    Document,
    DocumentTask,
)
from app.services import task_state
from app.tasks.celery_app import QUEUE_ANNOTATE, celery_app
from app.tasks.events import append_event

log = logging.getLogger("annotate")

AUTHOR = "ai-doc-lint"
SEV_TAG = {"error": "【错误】", "warning": "【警告】", "info": "【提示】"}


def enqueue_annotate(task_id: uuid.UUID) -> None:
    run_annotate.apply_async(args=[str(task_id)], queue=QUEUE_ANNOTATE)


# ---------------- 数据准备 ----------------


def _active_findings(db: Session, document_id: uuid.UUID) -> list[CheckFinding]:
    rows = (
        db.query(CheckFinding)
        .filter(
            CheckFinding.document_id == document_id,
            CheckFinding.status == "open",
        )
        .order_by(CheckFinding.id)
        .all()
    )
    return rows


def _load_plaintext(db: Session, document: Document) -> str | None:
    """读取解析任务落盘的纯文本（非 docx 输入生成批注版时附带原合同全文）。"""
    parse_task = (
        db.query(DocumentTask)
        .filter(
            DocumentTask.document_id == document.id,
            DocumentTask.task_type == "parse",
        )
        .order_by(DocumentTask.created_at.desc())
        .first()
    )
    if parse_task is None:
        return None
    key = (parse_task.result_refs or {}).get("plaintext")
    if not key:
        return None
    try:
        return storage.get_object_bytes(key).decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return None


def _comment_text(finding: CheckFinding) -> str:
    parts = [SEV_TAG.get(finding.severity, "【提示】") + finding.message]
    if finding.suggestion:
        parts.append("建议：" + finding.suggestion)
    return "\n".join(parts)


def _all_paragraphs(doc: DocxDocument):
    """正文段落 + 表格单元格段落，按文档顺序返回。"""
    yield from doc.paragraphs
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                yield from cell.paragraphs


def _norm(text: str) -> str:
    return "".join((text or "").split())


# ---------------- docx 批注 ----------------


def _annotate_docx(data: bytes, findings: list[CheckFinding]) -> bytes:
    doc = DocxDocument(io.BytesIO(data))
    paragraphs = list(_all_paragraphs(doc))
    prepared = [(f, _comment_text(f)) for f in findings]
    unmatched: list[tuple[CheckFinding, str]] = []

    for finding, text in prepared:
        snippet = _norm((finding.location or {}).get("snippet", ""))
        target = None
        if snippet:
            target = next(
                (p for p in paragraphs if snippet and snippet in _norm(p.text)),
                None,
            )
        if target is not None and target.runs:
            # 批注锚定该段落的全部 run（python-docx 1.2 原生注释）
            doc.add_comment(
                runs=target.runs, text=text,
                author=AUTHOR, initials="ADL",
            )
        else:
            unmatched.append((finding, text))

    if unmatched:
        doc.add_paragraph()
        heading = doc.add_paragraph()
        heading.add_run("问题汇总（未能定位到原文位置）").bold = True
        for finding, text in unmatched:
            p = doc.add_paragraph(text)
            p.paragraph_format.left_indent = None

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


# ---------------- 全文+问题清单 docx（pdf/txt/md） ----------------


def _build_full_doc(filename: str, findings: list[CheckFinding], plaintext: str) -> bytes:
    """问题清单（前） + 原合同全文（后，可编辑）——独立工具闭环：用户下载后可改全文再覆盖重传。"""
    doc = DocxDocument()
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.add_run(f"《{filename}》问题清单").bold = True
    doc.add_paragraph(
        "由 ai-doc-lint 自动生成；AI 校对辅助，不构成法律意见。"
    )

    for idx, finding in enumerate(findings, 1):
        head = doc.add_paragraph()
        head.add_run(
            f"{idx}. {SEV_TAG.get(finding.severity, '【提示】')}"
            f"{finding.message}"
        ).bold = True
        snippet = (finding.location or {}).get("snippet")
        if snippet:
            doc.add_paragraph(f"原文：…{snippet}…")
        if finding.suggestion:
            doc.add_paragraph(f"建议：{finding.suggestion}")

    # 原合同全文（可编辑；允许用户在下载物中直接修改后覆盖重传）
    if plaintext and plaintext.strip():
        doc.add_page_break()
        full = doc.add_paragraph()
        full.add_run("原合同全文（可编辑，修改后可直接覆盖重传）").bold = True
        doc.add_paragraph(
            "以下为原文件解析出的完整文本，供直接修改使用。"
        )
        for line in plaintext.splitlines():
            doc.add_paragraph(line)

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


# ---------------- 任务主体 ----------------


@celery_app.task(name="app.tasks.annotate.run_annotate", bind=True, max_retries=2)
def run_annotate(self, task_id_str: str):
    db = SessionLocal()
    try:
        task = db.get(DocumentTask, uuid.UUID(task_id_str))
        if task is None:
            log.warning("annotate task %s not found", task_id_str)
            return
        if task.status != STATUS_PENDING:
            log.info("annotate task %s status %s, skip", task_id_str, task.status)
            return

        task_state.change_status(
            db, task, task_state.STATUS_RUNNING,
            event_type="task_started", stage="init",
            message="开始生成批注版",
            fields={"celery_task_id": self.request.id},
        )

        document = db.get(Document, task.document_id)
        if document is None:
            task_state.change_status(
                db, task, task_state.STATUS_FAILED,
                event_type="task_failed", stage="error", message="文档不存在",
                fields={"error_message": "文档不存在"},
            )
            return

        findings = _active_findings(db, document.id)
        if not findings:
            task_state.change_status(
                db, task, task_state.STATUS_FAILED,
                event_type="task_failed", stage="error",
                message="没有待处理问题，无需生成批注版",
                fields={"error_message": "没有待处理问题，无需生成批注版"},
            )
            return

        data = storage.get_object_bytes(document.storage_key)
        ext = (document.ext or "").lower()
        if ext == "docx":
            output = _annotate_docx(data, findings)
            label = "批注版文档"
        else:
            # 非 docx：问题清单 + 原合同全文（P1-3 修复：下载物须可直接修改再覆盖重传）
            plaintext = _load_plaintext(db, document)
            output = _build_full_doc(document.filename, findings, plaintext or "")
            label = "问题清单+全文"

        key = f"artifacts/{document.id}/annotated/{uuid.uuid4().hex}.docx"
        storage.put_object(
            key, output,
            content_type="application/vnd.openxmlformats-officedocument"
                         ".wordprocessingml.document",
        )
        db.add(Artifact(
            document_id=document.id, task_id=task.id,
            kind=ART_ANNOTATED, storage_key=key,
            content_type="application/vnd.openxmlformats-officedocument"
                         ".wordprocessingml.document",
            size_bytes=len(output),
        ))
        db.flush()

        append_event(
            db, task, "stage_progress", stage="annotate",
            message=f"{label}已生成",
        )
        task_state.change_status(
            db, task, task_state.STATUS_PARSED,
            event_type="task_succeeded", stage="done",
            message=f"{label}已生成",
            fields={"result_refs": {"annotated": key}},
        )
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log.exception("annotate task %s failed: %s", task_id_str, exc)
        raise self.retry(exc=exc, countdown=5)
    finally:
        db.close()
