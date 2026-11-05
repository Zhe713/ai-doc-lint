"""annotate（批注版生成）任务。

同格式回写、原文档零改写，只加注释层：
- pdf：pypdfium2 定位字符坐标，pypdf 写高亮注解（按严重程度着色），
  点击高亮可看批注；定位不到的问题汇总成一条便签注解放在首页；
- docx：python-docx 原生 add_comment 写真 Word 批注；
  定位不到的问题汇总成一条批注挂在首个含 run 的段落；
- txt/md：在命中行下一行插入「【AI批注·级别】…」批注行；
  定位不到的问题在文件开头批注区集中列出。

产物入 MinIO（kind=annotated），result_refs.annotated 指向存储键。
"""

import io
import logging
import re
import uuid

import pypdfium2 as pdfium
from docx import Document as DocxDocument
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Highlight, Text as PdfText
from pypdf.generic import (
    ArrayObject,
    FloatObject,
    NameObject,
    TextStringObject,
)

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
SEV_COLOR = {"error": "ff0000", "warning": "ffff00", "info": "3399ff"}
MIME_MAP = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document",
    "txt": "text/plain",
    "md": "text/markdown",
}

_XML_ILLEGAL_RE = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff\ud800-\udfff]"
)


def _clean(text: str) -> str:
    return _XML_ILLEGAL_RE.sub("", text or "")


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


def _comment_text(finding: CheckFinding) -> str:
    parts = [SEV_TAG.get(finding.severity, "【提示】") + finding.message]
    if finding.suggestion:
        parts.append("建议：" + finding.suggestion)
    return _clean("\n".join(parts))


def _norm(text: str) -> str:
    return "".join((text or "").split())


def _all_paragraphs(doc: DocxDocument):
    """正文段落 + 表格单元格段落，按文档顺序返回。"""
    yield from doc.paragraphs
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                yield from cell.paragraphs


# ---------------- pdf 批注 ----------------


def _pdf_page_norm_map(tp: pdfium.PdfTextPage):
    """返回 (去空白拼接文本, 归一化位置->字符下标映射)。"""
    n_chars = tp.count_chars()
    norm_chars = []
    index_map = []
    for i in range(n_chars):
        piece = tp.get_text_range(i, 1)
        for ch in piece:
            if not ch.isspace():
                norm_chars.append(ch)
                index_map.append(i)
    return "".join(norm_chars), index_map


def _locate_pdf(pdf: pdfium.PdfDocument, snippet: str):
    target = _norm(snippet)
    if not target:
        return None
    for page_idx in range(len(pdf)):
        tp = pdf[page_idx].get_textpage()
        norm_text, index_map = _pdf_page_norm_map(tp)
        pos = norm_text.find(target)
        if pos >= 0:
            char_indices = sorted(set(index_map[pos:pos + len(target)]))
            return page_idx, char_indices
    return None


def _group_line_rects(tp: pdfium.PdfTextPage, char_indices: list[int]):
    """把字符框按行分组并合并，返回 (left, bottom, right, top) 列表。"""
    lines = {}
    for i in char_indices:
        left, bottom, right, top = tp.get_charbox(i)
        key = round(top, 1)
        if key in lines:
            pl, pb, pr, pt = lines[key]
            lines[key] = (min(pl, left), min(pb, bottom),
                          max(pr, right), max(pt, top))
        else:
            lines[key] = (left, bottom, right, top)
    return list(lines.values())


def _unmatched_note_text(items: list[CheckFinding]) -> str:
    lines = ["以下问题未能定位到原文位置："]
    for idx, finding in enumerate(items, 1):
        lines.append(
            f"{idx}. {SEV_TAG.get(finding.severity, '【提示】')}"
            f"{_comment_text(finding)}"
        )
    return "\n".join(lines)


def _annotate_pdf(data: bytes, findings: list[CheckFinding]) -> bytes:
    pdf = pdfium.PdfDocument(data)
    located = []
    unmatched = []

    for finding in findings:
        snippet = (finding.location or {}).get("snippet", "")
        hit = _locate_pdf(pdf, snippet)
        if hit is None:
            unmatched.append(finding)
        else:
            located.append((finding, hit[0], hit[1]))

    reader = PdfReader(io.BytesIO(data))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)

    for finding, page_idx, char_indices in located:
        tp = pdf[page_idx].get_textpage()
        line_rects = _group_line_rects(tp, char_indices)
        quads = ArrayObject()
        for left, bottom, right, top in line_rects:
            quads.extend([
                FloatObject(left), FloatObject(top),
                FloatObject(right), FloatObject(top),
                FloatObject(left), FloatObject(bottom),
                FloatObject(right), FloatObject(bottom),
            ])
        big_rect = (
            min(r[0] for r in line_rects),
            min(r[1] for r in line_rects),
            max(r[2] for r in line_rects),
            max(r[3] for r in line_rects),
        )
        highlight = Highlight(
            rect=big_rect,
            quad_points=quads,
            highlight_color=SEV_COLOR.get(finding.severity, "ffff00"),
            title_bar=AUTHOR,
        )
        highlight[NameObject("/Contents")] = TextStringObject(
            _comment_text(finding)
        )
        writer.add_annotation(page_idx, highlight)

    if unmatched:
        first_page = pdf[0]
        width, height = first_page.get_size()
        note = PdfText(
            rect=(10, height - 25, 26, height - 10),
            text=_unmatched_note_text(unmatched),
        )
        writer.add_annotation(0, note)

    out = io.BytesIO()
    writer.write(out)
    pdf.close()
    return out.getvalue()


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
                (p for p in paragraphs if snippet in _norm(p.text)),
                None,
            )
        if target is not None and target.runs:
            doc.add_comment(
                runs=target.runs, text=text,
                author=AUTHOR, initials="ADL",
            )
        else:
            unmatched.append((finding, text))

    if unmatched:
        anchor = next((p for p in paragraphs if p.runs), None)
        if anchor is not None:
            merged = "\n".join(text for _, text in unmatched)
            doc.add_comment(
                runs=anchor.runs, text=merged,
                author=AUTHOR, initials="ADL",
            )
        else:
            for finding, text in unmatched:
                doc.add_paragraph(text)

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


# ---------------- txt/md 批注 ----------------


def _text_norm_map(text: str):
    norm_chars = []
    line_map = []
    for line_idx, line in enumerate(text.splitlines()):
        for ch in line:
            if not ch.isspace():
                norm_chars.append(ch)
                line_map.append(line_idx)
    return "".join(norm_chars), line_map


def _locate_text_line(text: str, snippet: str):
    target = _norm(snippet)
    if not target:
        return None
    norm_text, line_map = _text_norm_map(text)
    pos = norm_text.find(target)
    if pos < 0:
        return None
    return line_map[pos]


def _annotate_text(data: bytes, findings: list[CheckFinding]) -> bytes:
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    inserts: dict[int, list[str]] = {}
    unmatched = []

    for finding in findings:
        snippet = (finding.location or {}).get("snippet", "")
        line_idx = _locate_text_line(text, snippet)
        if line_idx is None:
            unmatched.append(finding)
        else:
            inserts.setdefault(line_idx, []).append(
                f"【AI批注·{finding.severity}】{_comment_text(finding)}"
            )

    header = []
    if unmatched:
        header.append("===== AI 批注（未定位问题）=====")
        for idx, finding in enumerate(unmatched, 1):
            header.append(
                f"{idx}. {SEV_TAG.get(finding.severity, '【提示】')}"
                f"{_comment_text(finding)}"
            )
        header.append("===== 以下为原文 =====")

    out_lines = []
    out_lines.extend(header)
    for idx, line in enumerate(lines):
        out_lines.append(line)
        if idx in inserts:
            out_lines.extend(inserts[idx])

    result = "\n".join(out_lines)
    if text.endswith("\n"):
        result += "\n"
    return result.encode("utf-8")


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
            label = "批注版Word"
        elif ext == "pdf":
            output = _annotate_pdf(data, findings)
            label = "批注版PDF"
        else:
            output = _annotate_text(data, findings)
            label = "批注版文本"

        content_type = MIME_MAP.get(ext, "application/octet-stream")
        key = f"artifacts/{document.id}/annotated/{uuid.uuid4().hex}.{ext}"
        storage.put_object(key, output, content_type=content_type)
        db.add(Artifact(
            document_id=document.id, task_id=task.id,
            kind=ART_ANNOTATED, storage_key=key,
            content_type=content_type,
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
        if self.request.retries >= self.max_retries:
            try:
                failed_task = db.get(DocumentTask, uuid.UUID(task_id_str))
                if failed_task is not None and failed_task.status == task_state.STATUS_RUNNING:
                    task_state.change_status(
                        db, failed_task, task_state.STATUS_FAILED,
                        event_type="task_failed", stage="error",
                        message=str(exc)[:500],
                        fields={"error_message": str(exc)[:500]},
                    )
            except Exception:  # noqa: BLE001
                db.rollback()
            raise
        raise self.retry(exc=exc, countdown=5)
    finally:
        db.close()
