"""解析后闸门三选一 + 取消：用同步假函数替代 Celery 入队（eager）。"""

import uuid

import pytest

from app.models.document import (
    STATUS_AWAITING,
    STATUS_PARSED,
    Document,
    DocumentTask,
)
from app.services import task_state
from conftest import TestSessionLocal
from tests.test_intake import _auth


def _install_fake(monkeypatch):
    """按文件名模拟解析结果；retry_ocr 后第二次执行（attempts>=1）走 OCR 成功路径。"""

    def fake_enqueue(task_id):
        db = TestSessionLocal()
        try:
            task = db.get(DocumentTask, uuid.UUID(str(task_id)))
            if task is None or task.status not in ("pending", STATUS_AWAITING):
                return
            doc = db.get(Document, task.document_id)
            task_state.change_status(
                db, task, task_state.STATUS_RUNNING, event_type="task_started", stage="init"
            )
            if doc.filename == "ok.txt":
                task_state.change_status(
                    db, task, task_state.STATUS_PARSED, event_type="task_parsed", stage="done",
                    fields={"stats": {"page_count": 1, "char_count": 11, "table_count": 0,
                                      "chars_per_page": 11.0, "ocr_used": False}},
                )
            elif doc.filename == "scan.pdf":
                if task.attempts >= 1:
                    task_state.change_status(
                        db, task, task_state.STATUS_PARSED, event_type="task_parsed", stage="ocr",
                        fields={"stats": {"page_count": 1, "char_count": 5, "table_count": 0,
                                          "chars_per_page": 5.0, "ocr_used": True}},
                    )
                else:
                    task_state.change_status(
                        db, task, task_state.STATUS_AWAITING, event_type="gate", stage="parse",
                        fields={
                            "gate_reason": "ocr_required",
                            "gate_payload": {"chars_per_page": 0, "min_chars_per_page": 20},
                        },
                    )
            elif doc.filename == "broken.pdf":
                task_state.change_status(
                    db, task, task_state.STATUS_AWAITING, event_type="gate", stage="parse",
                    fields={
                        "gate_reason": "parse_failed",
                        "error_code": "parse_failed",
                        "error_message": "damaged pdf",
                    },
                )
        finally:
            db.close()

    monkeypatch.setattr("app.api.documents.enqueue_parse", fake_enqueue)


def _upload_one(client, headers, name, content=b"data"):
    resp = client.post(
        "/api/v1/documents/upload",
        files={"files": (name, content, "application/octet-stream")},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["tasks"][0]["task_id"]


def test_happy_path_parsed(client, monkeypatch):
    _install_fake(monkeypatch)
    headers = _auth(client, "gate_ok")
    tid = _upload_one(client, headers, "ok.txt", b"hello world")
    detail = client.get(f"/api/v1/tasks/{tid}", headers=headers).json()
    assert detail["status"] == STATUS_PARSED
    assert detail["stats"]["char_count"] == 11
    assert len(detail["events"]) >= 2


def test_ocr_gate_retry_then_parsed(client, monkeypatch):
    _install_fake(monkeypatch)
    headers = _auth(client, "gate_ocr")
    tid = _upload_one(client, headers, "scan.pdf")
    detail = client.get(f"/api/v1/tasks/{tid}", headers=headers).json()
    assert detail["status"] == STATUS_AWAITING
    assert detail["gate_reason"] == "ocr_required"

    # ocr_required 不允许“带警告继续”
    bad = client.post(f"/api/v1/tasks/{tid}/decision", headers=headers,
                      json={"action": "continue_with_warnings"})
    assert bad.status_code == 409

    ok = client.post(f"/api/v1/tasks/{tid}/decision", headers=headers,
                     json={"action": "retry_ocr"})
    assert ok.status_code == 200
    detail = client.get(f"/api/v1/tasks/{tid}", headers=headers).json()
    assert detail["status"] == STATUS_PARSED
    assert detail["stats"]["ocr_used"] is True


def test_parse_failed_gate_continue_or_cancel(client, monkeypatch):
    _install_fake(monkeypatch)
    headers = _auth(client, "gate_fail")

    # 分支一：带警告继续
    tid = _upload_one(client, headers, "broken.pdf")
    resp = client.post(f"/api/v1/tasks/{tid}/decision", headers=headers,
                       json={"action": "continue_with_warnings"})
    assert resp.status_code == 200
    detail = client.get(f"/api/v1/tasks/{tid}", headers=headers).json()
    assert detail["status"] == STATUS_PARSED
    assert any(w.get("code") == "user_continued_with_warning" for w in detail["warnings"])

    # 分支二：取消
    tid2 = _upload_one(client, headers, "broken.pdf")
    resp2 = client.post(f"/api/v1/tasks/{tid2}/decision", headers=headers,
                        json={"action": "cancel"})
    assert resp2.status_code == 200
    detail2 = client.get(f"/api/v1/tasks/{tid2}", headers=headers).json()
    assert detail2["status"] == "cancelled"


def test_cancel_pending_task(client, monkeypatch):
    # 入队替换为 no-op，任务保持 pending，可直接取消
    monkeypatch.setattr("app.api.documents.enqueue_parse", lambda task_id: None)
    headers = _auth(client, "gate_cancel")
    tid = _upload_one(client, headers, "ok.txt", b"hi")
    resp = client.post(f"/api/v1/tasks/{tid}/cancel", headers=headers)
    assert resp.status_code == 200
    detail = client.get(f"/api/v1/tasks/{tid}", headers=headers).json()
    assert detail["status"] == "cancelled"


def test_decision_requires_awaiting_state(client, monkeypatch):
    _install_fake(monkeypatch)
    headers = _auth(client, "gate_state")
    tid = _upload_one(client, headers, "ok.txt", b"hello world")
    # 已 parsed 的任务再决策 → 409
    resp = client.post(f"/api/v1/tasks/{tid}/decision", headers=headers,
                       json={"action": "cancel"})
    assert resp.status_code == 409
