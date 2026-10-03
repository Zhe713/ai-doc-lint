"""报告页对话助手测试：L1 规则直答、L2 指代/澄清、L3 function calling 与错误降级。"""

import uuid

import pytest

from app.models.document import CheckFinding
from conftest import TestSessionLocal
from tests.test_intake import _auth
from tests.test_findings_api import _upload_doc, _user_id


@pytest.fixture(autouse=True)
def _patch_session_local(monkeypatch):
    # SSE 生成器内部自建会话，默认指向 dev 库，测试中替换为测试库
    monkeypatch.setattr("app.api.chat.SessionLocal", TestSessionLocal)


def _seed_findings(doc_id: str, user_id, specs: list[dict]):
    db = TestSessionLocal()
    try:
        for spec in specs:
            db.add(CheckFinding(
                document_id=uuid.UUID(doc_id), user_id=user_id,
                checker=spec.get("checker", "format"),
                rule_id=spec.get("rule_id", "fmt.x"),
                severity=spec.get("severity", "warning"),
                message=spec["message"],
                suggestion=spec.get("suggestion"),
                location=spec.get("location"),
                status="open",
            ))
        db.commit()
    finally:
        db.close()


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
            import json
            events.append(json.loads(line[5:].strip()))
    return events


def _assistant_route(client, headers, session_id):
    resp = client.get(f"/api/v1/chat/sessions/{session_id}", headers=headers)
    msgs = resp.json()["messages"]
    return [m for m in msgs if m["role"] == "assistant"]


def test_l1_list_findings(client, monkeypatch):
    monkeypatch.setattr("app.api.documents.enqueue_parse", lambda task_id: None)
    headers = _auth(client, "chat_l1")
    uid = _user_id("chat_l1")
    doc_id = _upload_doc(client, headers)
    _seed_findings(doc_id, uid, [
        {"message": "纸张尺寸不规范", "severity": "warning"},
        {"message": "缺少违约责任", "severity": "error"},
    ])
    sid = _make_session(client, headers, doc_id)

    events = _post(client, headers, sid, "列出所有问题")
    delta = "".join(e.get("text", "") for e in events if e["type"] == "delta")
    assert "共 2 个待处理问题" in delta
    assert "缺少违约责任" in delta

    assistants = _assistant_route(client, headers, sid)
    assert assistants[-1]["route_layer"] == "l1_rule"


def test_l1_summary(client, monkeypatch):
    monkeypatch.setattr("app.api.documents.enqueue_parse", lambda task_id: None)
    headers = _auth(client, "chat_sum")
    uid = _user_id("chat_sum")
    doc_id = _upload_doc(client, headers)
    _seed_findings(doc_id, uid, [{"message": "错别字问题"}])
    sid = _make_session(client, headers, doc_id)

    events = _post(client, headers, sid, "总结一下", button_intent="summarize")
    delta = "".join(e.get("text", "") for e in events if e["type"] == "delta")
    assert "待处理" in delta


def test_l2_clarify_multiple(client, monkeypatch):
    monkeypatch.setattr("app.api.documents.enqueue_parse", lambda task_id: None)
    headers = _auth(client, "chat_clar")
    uid = _user_id("chat_clar")
    doc_id = _upload_doc(client, headers)
    _seed_findings(doc_id, uid, [
        {"message": "问题甲"}, {"message": "问题乙"},
    ])
    sid = _make_session(client, headers, doc_id)

    _post(client, headers, sid, "列出所有问题")
    events = _post(client, headers, sid, "这条怎么改")
    delta = "".join(e.get("text", "") for e in events if e["type"] == "delta")
    assert "哪一条" in delta
    assert "问题甲" in delta

    assistants = _assistant_route(client, headers, sid)
    assert assistants[-1]["route_layer"] == "l2_context"


def test_l2_single_finding_suggest(client, monkeypatch):
    monkeypatch.setattr("app.api.documents.enqueue_parse", lambda task_id: None)
    headers = _auth(client, "chat_single")
    uid = _user_id("chat_single")
    doc_id = _upload_doc(client, headers)
    _seed_findings(doc_id, uid, [{
        "message": "履行期限不明",
        "suggestion": "明确具体交付日期",
    }])
    sid = _make_session(client, headers, doc_id)

    events = _post(client, headers, sid, "这个怎么改")
    delta = "".join(e.get("text", "") for e in events if e["type"] == "delta")
    assert "明确具体交付日期" in delta


def test_l3_agent_path(client, monkeypatch):
    monkeypatch.setattr("app.api.documents.enqueue_parse", lambda task_id: None)

    def fake_run_l3(db, document_id, history, text):
        yield "delta", "根据文档内容，"
        yield "delta", "未发现相关约定。"
        yield "end", {
            "tool_calls": [{"name": "get_findings", "args": {}}],
            "model": "qwen-plus", "prompt_tokens": 100,
            "completion_tokens": 20,
        }

    monkeypatch.setattr("app.chat.l3_agent.run_l3", fake_run_l3)
    headers = _auth(client, "chat_l3")
    doc_id = _upload_doc(client, headers)
    sid = _make_session(client, headers, doc_id)

    events = _post(client, headers, sid, "请问这个条款和行业惯例相比如何")
    delta = "".join(e.get("text", "") for e in events if e["type"] == "delta")
    assert "未发现相关约定" in delta
    assert any(e["type"] == "done" for e in events)

    assistants = _assistant_route(client, headers, sid)
    assert assistants[-1]["route_layer"] == "l3_agent"


def test_l3_not_configured_error(client, monkeypatch):
    monkeypatch.setattr("app.api.documents.enqueue_parse", lambda task_id: None)

    def fake_run_l3(db, document_id, history, text):
        from app.llm.client import LLMNotConfiguredError
        raise LLMNotConfiguredError("no key")
        yield  # pragma: no cover  使其成为生成器函数

    monkeypatch.setattr("app.chat.l3_agent.run_l3", fake_run_l3)
    headers = _auth(client, "chat_l3err")
    doc_id = _upload_doc(client, headers)
    sid = _make_session(client, headers, doc_id)

    events = _post(client, headers, sid, "帮我对比行业惯例，跨领域分析")
    assert any(e["type"] == "error" and "大模型" in e.get("text", "")
               for e in events)
