"""任务状态机：合法跳转、非法跳转、组计数与文档状态跟随。"""

import uuid as uuid_lib

import pytest

from app.core.security import hash_password
from app.models.document import (
    STATUS_AWAITING,
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_PARSED,
    STATUS_PENDING,
    STATUS_RUNNING,
    Document,
    DocumentTask,
    TaskGroup,
)
from app.models.user import User
from app.services import task_state
from app.services.setup_service import ensure_roles
from conftest import TestSessionLocal


def _make_user_and_task():
    db = TestSessionLocal()
    roles = ensure_roles(db)
    uname = f"sm_user_{uuid_lib.uuid4().hex[:8]}"
    user = User(username=uname, password_hash=hash_password("Pass123456"))
    db.add(user)
    db.flush()
    # 与真实受理一致：建组时该任务已计入 pending
    group = TaskGroup(user_id=user.id, total=1, pending=1)
    db.add(group)
    db.flush()
    doc = Document(
        user_id=user.id,
        filename="a.txt",
        size_bytes=10,
        content_type="text/plain",
        sha256="x",
        storage_key="dev/a.txt",
        ext="txt",
    )
    db.add(doc)
    db.flush()
    task = DocumentTask(
        document_id=doc.id, user_id=user.id, group_id=group.id, task_type="parse"
    )
    db.add(task)
    db.commit()
    return user.id, group.id, doc.id, task.id


def test_legal_path_pending_running_parsed():
    _, group_id, doc_id, task_id = _make_user_and_task()
    db = TestSessionLocal()
    try:
        task = db.get(DocumentTask, task_id)
        task_state.change_status(db, task, STATUS_RUNNING, event_type="task_started", stage="init")
        task_state.change_status(db, task, STATUS_PARSED, event_type="task_parsed", stage="done")
        db.commit()

        group = db.get(TaskGroup, group_id)
        doc = db.get(Document, doc_id)
        assert group.succeeded == 1
        assert group.pending == 0
        assert group.running == 0
        assert doc.status == STATUS_PARSED
    finally:
        db.close()


def test_illegal_skip_transition():
    _, _, _, task_id = _make_user_and_task()
    db = TestSessionLocal()
    try:
        task = db.get(DocumentTask, task_id)
        with pytest.raises(task_state.IllegalTransition):
            task_state.change_status(db, task, STATUS_PARSED, event_type="x")
    finally:
        db.close()


def test_terminal_state_is_frozen():
    _, _, _, task_id = _make_user_and_task()
    db = TestSessionLocal()
    try:
        task = db.get(DocumentTask, task_id)
        task_state.change_status(db, task, STATUS_RUNNING, event_type="s", stage="i")
        task_state.change_status(db, task, STATUS_PARSED, event_type="p", stage="d")
        db.commit()
        with pytest.raises(task_state.IllegalTransition):
            task_state.change_status(db, task, STATUS_RUNNING, event_type="back")
    finally:
        db.close()


def test_gate_three_ways():
    # 同一起点 awaiting 的三个合法出口分别验证
    for target in (STATUS_PENDING, STATUS_PARSED, STATUS_CANCELLED):
        _, _, _, task_id = _make_user_and_task()
        db = TestSessionLocal()
        try:
            task = db.get(DocumentTask, task_id)
            task_state.change_status(db, task, STATUS_RUNNING, event_type="s", stage="i")
            task_state.change_status(
                db, task, STATUS_AWAITING, event_type="gate",
                stage="parse", fields={"gate_reason": "ocr_required"},
            )
            db.commit()
            task_state.change_status(db, task, target, event_type="decision", stage="gate")
            db.commit()
            assert task.status == target
        finally:
            db.close()


def test_failed_counts_in_group():
    _, group_id, _, task_id = _make_user_and_task()
    db = TestSessionLocal()
    try:
        task = db.get(DocumentTask, task_id)
        task_state.change_status(db, task, STATUS_RUNNING, event_type="s", stage="i")
        task_state.change_status(
            db, task, STATUS_FAILED, event_type="f", stage="error",
            fields={"error_code": "parse_failed", "error_message": "boom"},
        )
        db.commit()
        group = db.get(TaskGroup, group_id)
        assert group.failed == 1
        assert group.finished_at is not None
    finally:
        db.close()
