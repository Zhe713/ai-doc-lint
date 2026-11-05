"""chat 助手多轮上下文记忆的持久化测试。

覆盖四个记忆面：
1. 消息持久化：user/assistant 消息落库，重新开 Session（模拟重启）后完整可恢复；
2. LLM 上下文：走 L3 时，前几轮 user/assistant 消息真实进入模型 history，
   且本轮 user 消息不重复出现（回归「重复拼接」缺陷）；
3. 槽位记忆：L2 通过上一轮 assistant 消息的 payload.finding_id 做跨轮指代继承；
4. 会话边界：会话按用户隔离，他人不可读写；历史窗口最近 8 条截断。
"""

import json
import uuid

import pytest

from app.models.chat import ChatMessage
from app.chat.service import _history
from conftest import TestSessionLocal
from tests.test_intake import _auth
from tests.test_findings_api import _upload_doc, _user_id


@pytest.fixture(autouse=True)
def _patch_session_local(monkeypatch):
    # SSE 生成器内部自建会话，默认指向 dev 库，测试中替换为测试库
    monkeypatch.setattr("app.api.chat.SessionLocal", TestSessionLocal)


def _seed_findings(db, doc_id: str, user_id, specs: list[dict]):
    from app.models.document import CheckFinding
    for spec in specs:
        db.add(CheckFinding(
            document_id=uuid.UUID(doc_id), user_id=user_id,
            checker=spec.get("checker", "format"),
            rule_id=spec.get("rule_id", "fmt.x"),
            severity=spec.get("severity", "warning"),
            message=spec["message"],
            suggestion=spec.get("suggestion"),
            status="open",
        ))
    db.commit()


def _make_session(client, headers, doc_id: str) -> str:
    resp = client.post(
        "/api/v1/chat/sessions", headers=headers,
        json={"document_id": doc_id},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _post(client, headers, session_id: str, content: str,
          button_intent=None) -> list[dict]:
    resp = client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        headers=headers,
        json={"content": content, "button_intent": button_intent},
    )
    assert resp.status_code == 200, resp.text
    events = []
    for line in resp.text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            events.append(json.loads(line[5:].strip()))
    return events


def _delta(events: list[dict]) -> str:
    return "".join(e.get("text", "") for e in events if e["type"] == "delta")


def _get_messages(client, headers, session_id: str) -> list[dict]:
    resp = client.get(f"/api/v1/chat/sessions/{session_id}", headers=headers)
    assert resp.status_code == 200
    return resp.json()["messages"]


# ---------------- 1. 消息持久化与恢复 ----------------


def test_messages_persist_and_survive_new_session(client, monkeypatch):
    """两轮对话后，模拟重启（新开 DB Session）取回全部消息，顺序与内容完整。"""
    monkeypatch.setattr("app.api.documents.enqueue_parse", lambda task_id: None)
    headers = _auth(client, "mem_persist")
    uid = _user_id("mem_persist")
    doc_id = _upload_doc(client, headers)
    db = TestSessionLocal()
    try:
        _seed_findings(db, doc_id, uid, [
            {"message": "纸张尺寸不规范"},
            {"message": "缺少违约责任"},
        ])
    finally:
        db.close()
    sid = _make_session(client, headers, doc_id)

    _post(client, headers, sid, "列出所有问题")      # L1
    _post(client, headers, sid, "第2条怎么改")       # L2 序数锁定

    # 模拟重启：全新 Session 直查测试库
    db2 = TestSessionLocal()
    try:
        rows = (
            db2.query(ChatMessage)
            .filter(ChatMessage.session_id == uuid.UUID(sid))
            .order_by(ChatMessage.id)
            .all()
        )
    finally:
        db2.close()

    roles = [m.role for m in rows]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert rows[0].content == "列出所有问题"
    assert rows[1].content.startswith("共 2 个待处理问题")
    assert rows[2].content == "第2条怎么改"
    # L2 的槽位记忆落进了 payload，重启后仍可审计
    assert rows[3].payload.get("slots", {}).get("ordinal") == 2


def test_get_session_restores_full_history(client, monkeypatch):
    """GET /chat/sessions/{id} 按序返回全部消息，前端刷新/恢复会话依赖它。"""
    monkeypatch.setattr("app.api.documents.enqueue_parse", lambda task_id: None)
    headers = _auth(client, "mem_restore")
    uid = _user_id("mem_restore")
    doc_id = _upload_doc(client, headers)
    db = TestSessionLocal()
    try:
        _seed_findings(db, doc_id, uid, [{
            "message": "履行期限不明", "suggestion": "明确具体交付日期",
        }])
    finally:
        db.close()
    sid = _make_session(client, headers, doc_id)

    _post(client, headers, sid, "列出所有问题")
    _post(client, headers, sid, "这条怎么改")

    msgs = _get_messages(client, headers, sid)
    assert len(msgs) == 4
    assert [(m["role"]) for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert msgs[0]["content"] == "列出所有问题"
    assert msgs[2]["content"] == "这条怎么改"
    # 单条 finding 时 L2 直接锁定，回答携带该条的建议（持久化后仍可读）
    assert "明确具体交付日期" in msgs[3]["content"]


# ---------------- 2. LLM 上下文记忆（L3） ----------------


def test_l3_history_carries_prior_turns(client, monkeypatch):
    """第二轮走 L3 时，模型收到的 history 必须包含第一轮的问答，
    且最后一条是本轮刚提交的 user 消息——这是「多轮记忆」的核心断言。"""
    monkeypatch.setattr("app.api.documents.enqueue_parse", lambda task_id: None)
    captured: dict = {}

    def fake_run_l3(db, document_id, history, text):
        captured["history"] = [dict(m) for m in history]
        captured["text"] = text
        yield "delta", "综合上文分析。"
        yield "end", {"tool_calls": [], "model": "qwen-plus",
                      "prompt_tokens": 10, "completion_tokens": 5}

    monkeypatch.setattr("app.chat.l3_agent.run_l3", fake_run_l3)
    headers = _auth(client, "mem_l3ctx")
    uid = _user_id("mem_l3ctx")
    doc_id = _upload_doc(client, headers)
    db = TestSessionLocal()
    try:
        _seed_findings(db, doc_id, uid, [{"message": "缺少违约责任"}])
    finally:
        db.close()
    sid = _make_session(client, headers, doc_id)

    _post(client, headers, sid, "列出所有问题")  # 第一轮：L1 直答
    # 第二轮：无 L1 关键词、无指代词，L1/L2 都不命中 → 升级 L3
    _post(client, headers, sid, "行业惯例与专业写法的差异如何评估")

    history = captured["history"]
    texts = [(m["role"], m["content"]) for m in history]
    assert ("user", "列出所有问题") in texts
    assert any(
        role == "assistant" and "缺少违约责任" in content
        for role, content in texts
    ), "第一轮的 assistant 回答应进入 L3 上下文"
    # 最后一条是本轮 user 消息，且 run_l3 收到的 user_text 与之一致
    assert history[-1]["role"] == "user"
    assert history[-1]["content"] == captured["text"]


def test_l3_current_user_message_not_duplicated(client, monkeypatch):
    """回归：L3 上下文里本轮用户消息只能出现一次（曾重复拼接两次）。"""
    monkeypatch.setattr("app.api.documents.enqueue_parse", lambda task_id: None)

    def fake_run_l3(db, document_id, history, text):
        captured = {"history": list(history)}
        fake_run_l3.captured = captured  # type: ignore[attr-defined]
        yield "delta", "ok"
        yield "end", {"tool_calls": [], "model": "m",
                      "prompt_tokens": 1, "completion_tokens": 1}

    monkeypatch.setattr("app.chat.l3_agent.run_l3", fake_run_l3)
    headers = _auth(client, "mem_l3dup")
    doc_id = _upload_doc(client, headers)
    sid = _make_session(client, headers, doc_id)

    text = "帮我对比行业惯例，跨领域分析一下"
    _post(client, headers, sid, text)

    history = fake_run_l3.captured["history"]  # type: ignore[attr-defined]
    occurrences = sum(
        1 for m in history
        if m["role"] == "user" and m["content"] == text
    )
    assert occurrences == 1, f"本轮 user 消息出现 {occurrences} 次，应恰为 1 次"


# ---------------- 3. L2 跨轮槽位记忆 ----------------


def test_l2_coref_inherits_finding_across_turns(client, monkeypatch):
    """三条 finding：先问列表，再「第3条怎么改」锁定，最后「它的建议是什么」
    应通过上一轮 payload.finding_id 指代继承第 3 条，而不是反问。"""
    monkeypatch.setattr("app.api.documents.enqueue_parse", lambda task_id: None)
    headers = _auth(client, "mem_coref")
    uid = _user_id("mem_coref")
    doc_id = _upload_doc(client, headers)
    db = TestSessionLocal()
    try:
        _seed_findings(db, doc_id, uid, [
            {"message": "问题一", "suggestion": "建议一"},
            {"message": "问题二", "suggestion": "建议二"},
            {"message": "缺少违约责任", "suggestion": "明确违约金比例"},
        ])
    finally:
        db.close()
    sid = _make_session(client, headers, doc_id)

    _post(client, headers, sid, "列出所有问题")
    _post(client, headers, sid, "第3条怎么改")
    events = _post(client, headers, sid, "它的建议是什么")  # 指代继承

    delta = _delta(events)
    assert "明确违约金比例" in delta, "跨轮指代应继承第 3 条的 finding_id"

    # 记忆落在库里：最后一条 assistant 的 payload.finding_id 可查、可审计
    msgs = _get_messages(client, headers, sid)
    assert msgs[-1]["content"] == delta
    db3 = TestSessionLocal()
    try:
        rows = (
            db3.query(ChatMessage)
            .filter(ChatMessage.session_id == uuid.UUID(sid),
                    ChatMessage.role == "assistant")
            .order_by(ChatMessage.id.desc())
            .first()
        )
        assert rows.payload.get("finding_id")
    finally:
        db3.close()


# ---------------- 4. 会话边界与窗口 ----------------


def test_session_isolated_between_users(client, monkeypatch):
    """会话按用户隔离：他人读返回 404，写返回 error 事件。"""
    monkeypatch.setattr("app.api.documents.enqueue_parse", lambda task_id: None)
    headers_a = _auth(client, "mem_iso_a")
    doc_id = _upload_doc(client, headers_a)
    sid = _make_session(client, headers_a, doc_id)

    headers_b = _auth(client, "mem_iso_b")

    resp = client.get(f"/api/v1/chat/sessions/{sid}", headers=headers_b)
    assert resp.status_code == 404

    resp = client.post(
        f"/api/v1/chat/sessions/{sid}/messages", headers=headers_b,
        json={"content": "越权提问"},
    )
    assert resp.status_code == 200  # SSE 通道
    events = []
    for line in resp.text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            events.append(json.loads(line[5:].strip()))
    assert any(e["type"] == "error" and "会话不存在" in e.get("text", "")
               for e in events)

    # A 的会话没有被写入 B 的消息
    msgs = _get_messages(client, headers_a, sid)
    assert all(m["content"] != "越权提问" for m in msgs)


def test_history_window_capped_at_8():
    """_history 只取最近 8 条——上下文窗口有界，不会随对话无限增长。"""
    from types import SimpleNamespace
    from app.models.chat import ChatMessage as CM

    sid = uuid.uuid4()
    built = []
    for i in range(12):
        role = "user" if i % 2 == 0 else "assistant"
        built.append(CM(session_id=sid, role=role, content=f"msg{i}"))

    class FakeQuery:
        def __init__(self, items):
            self._items = items

        def filter(self, *a, **k):
            return self

        def order_by(self, *a, **k):
            return self

        def all(self):
            return self._items

    class FakeDB:
        def query(self, model):
            return FakeQuery(built)

    result = _history(FakeDB(), SimpleNamespace(id=sid))
    assert len(result) == 8
    assert result[0]["content"] == "msg4"
    assert result[-1]["content"] == "msg11"
