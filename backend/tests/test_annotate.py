"""annotate 批注版任务测试：同格式回写。

覆盖：docx 原生批注、docx 未定位批注挂首段、txt 行内批注、
txt 未定位开头批注区、pdf 真实合同高亮注解、无问题拦截、
控制字符清洗与归属隔离。
"""

import io
import os
import uuid
import zipfile

import pytest
from docx import Document as DocxDocument

from app.db import storage
from app.models.document import (
    ART_ANNOTATED,
    Artifact,
    CheckFinding,
    Document,
    DocumentTask,
)
from conftest import TestSessionLocal
from sqlalchemy.orm import Session
from tests.test_intake import _auth, _make_user, _token

# golden 语料（真实合同）不随仓库分发（.gitignore），仅本地/内网环境存在；
# CI 上跳过依赖语料的用例，其余批注逻辑用合成 docx/txt 全覆盖
GOLDEN_PDF = "/app/corpus/acceptance_golden/build_01_建设工程施工合同.pdf"
_HAS_GOLDEN_PDF = os.path.exists(GOLDEN_PDF)


def _docx_bytes(paragraphs: list[str]) -> bytes:
    doc = DocxDocument()
    for text in paragraphs:
        doc.add_paragraph(text)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def _doc_text_from_docx(data: bytes) -> str:
    doc = DocxDocument(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs)


def _setup(*, ext="docx", original: bytes | None, findings: list[dict],
           username=None):
    db = TestSessionLocal()
    username = username or f"ann_{uuid.uuid4().hex[:8]}"
    _make_user(username)
    from app.models.user import User

    user = db.query(User).filter(User.username == username).one()

    orig_key = f"docs/{user.id}/orig.{ext}"
    storage.put_object(orig_key, original or b"",
                       content_type="application/octet-stream")
    doc = Document(
        user_id=user.id, filename=f"sample.{ext}", storage_key=orig_key,
        sha256="x" * 64, size_bytes=len(original or b""),
        content_type="text/plain", ext=ext, doc_type="contract",
        status="parsed",
    )
    db.add(doc)
    db.flush()

    for spec in findings:
        db.add(CheckFinding(
            document_id=doc.id, user_id=user.id,
            checker=spec.get("checker", "clause"),
            rule_id=spec.get("rule_id", "clause.breach"),
            severity=spec.get("severity", "warning"),
            location=spec.get("location"),
            message=spec["message"],
            suggestion=spec.get("suggestion"),
            status=spec.get("status", "open"),
        ))

    task = DocumentTask(
        group_id=None, document_id=doc.id, user_id=user.id,
        task_type="annotate", status="pending", max_attempts=1,
    )
    db.add(task)
    db.commit()
    return db, doc, task


def _run_task(task: DocumentTask):
    from app.tasks import annotate as ann_mod

    ann_mod.SessionLocal = TestSessionLocal
    ann_mod.run_annotate.run(str(task.id))


def _output_bytes(db: Session, task: DocumentTask) -> bytes:
    db.refresh(task)
    key = task.result_refs["annotated"]
    return storage.get_object_bytes(key)


def test_docx_native_comment():
    para = "甲方应在约定时间内交付合格货物，乙方按时验收。"
    original = _docx_bytes([para])
    db, doc, task = _setup(
        ext="docx", original=original,
        findings=[{
            "rule_id": "clause.performance", "severity": "warning",
            "message": "履行期限约定不明确",
            "suggestion": "明确具体交付日期",
            "location": {"snippet": "甲方应在约定时间内交付合格货物"},
        }],
    )
    _run_task(task)
    data = _output_bytes(db, task)

    zf = zipfile.ZipFile(io.BytesIO(data))
    comments = zf.read("word/comments.xml").decode("utf-8")
    assert "履行期限约定不明确" in comments
    assert "明确具体交付日期" in comments
    assert db.query(Artifact).filter(
        Artifact.document_id == doc.id, Artifact.kind == ART_ANNOTATED
    ).count() == 1
    db.close()


def test_unmatched_finding_as_comment():
    original = _docx_bytes(["这是一段没有任何定位线索的正文内容。"])
    db, doc, task = _setup(
        ext="docx", original=original,
        findings=[{
            "message": "缺少违约责任条款",
            "location": {"snippet": "原文里完全没有的句子"},
        }],
    )
    _run_task(task)
    data = _output_bytes(db, task)

    zf = zipfile.ZipFile(io.BytesIO(data))
    comments = zf.read("word/comments.xml").decode("utf-8")
    assert "缺少违约责任条款" in comments
    assert _doc_text_from_docx(data) == "这是一段没有任何定位线索的正文内容。"
    db.close()


def test_txt_inline_annotation():
    line = "甲方应在约定时间内交付合格货物。"
    db, doc, task = _setup(
        ext="txt", original=line.encode("utf-8"),
        findings=[{
            "message": "履行期限约定不明确",
            "severity": "warning",
            "location": {"snippet": "甲方应在约定时间内交付"},
        }],
    )
    _run_task(task)
    text = _output_bytes(db, task).decode("utf-8")
    lines = text.splitlines()
    assert line in lines
    idx = lines.index(line)
    assert "【AI批注·warning】" in lines[idx + 1]
    assert "履行期限约定不明确" in lines[idx + 1]
    db.close()


def test_txt_unmatched_header():
    line = "这是一段正文内容。"
    db, doc, task = _setup(
        ext="txt", original=line.encode("utf-8"),
        findings=[{
            "message": "缺少违约责任条款",
            "location": {"snippet": "原文里完全没有的句子"},
        }],
    )
    _run_task(task)
    text = _output_bytes(db, task).decode("utf-8")
    assert "未定位问题" in text
    assert "缺少违约责任条款" in text
    assert line in text
    db.close()


@pytest.mark.skipif(
    not _HAS_GOLDEN_PDF, reason="golden 语料未随仓库分发（.gitignore），仅本地环境可跑"
)
def test_pdf_highlight_annotation():
    with open(GOLDEN_PDF, "rb") as fh:
        original = fh.read()
    db, doc, task = _setup(
        ext="pdf", original=original,
        findings=[{
            "message": "测试高亮问题",
            "severity": "warning",
            "location": {"snippet": "合同"},
        }],
    )
    _run_task(task)
    data = _output_bytes(db, task)
    assert data[:5] == b"%PDF-"

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    found = False
    for page in reader.pages:
        for annotation in page.annotations or []:
            obj = annotation.get_object()
            if obj.get("/Subtype") == "/Highlight":
                contents = obj.get("/Contents")
                if contents and "测试高亮问题" in str(contents):
                    found = True
    assert found
    db.close()


def test_no_open_findings_fails():
    original = _docx_bytes(["正文内容。"])
    db, doc, task = _setup(
        ext="docx", original=original,
        findings=[{"message": "已处理的问题", "status": "fixed"}],
    )
    _run_task(task)
    db.refresh(task)
    assert task.status == "failed"
    assert "无需生成" in (task.error_message or "")
    db.close()


def test_control_chars_sanitized():
    from app.tasks.annotate import _clean

    assert _clean("a\x00b\x01c\x0bd") == "abcd"
    assert _clean("\t\n\r") == "\t\n\r"

    db, doc, task = _setup(
        ext="txt", original=b"body",
        findings=[{"message": "bad\x01char", "severity": "warning"}],
    )
    _run_task(task)
    text = _output_bytes(db, task).decode("utf-8")
    assert "badchar" in text
    db.close()


def test_annotate_api_ownership(client, monkeypatch):
    monkeypatch.setattr("app.api.documents.enqueue_parse", lambda task_id: None)
    headers = _auth(client, "ann_owner")
    resp = client.post(
        "/api/v1/documents/upload",
        files={"files": ("a.txt", b"hello", "text/plain")},
        headers=headers,
    )
    doc_id = resp.json()["tasks"][0]["document_id"]

    created = client.post(f"/api/v1/documents/{doc_id}/annotate", headers=headers)
    assert created.status_code == 201

    _make_user("ann_other")
    other = {"Authorization": f"Bearer {_token(client, 'ann_other')}"}
    resp = client.post(f"/api/v1/documents/{doc_id}/annotate", headers=other)
    assert resp.status_code == 404
