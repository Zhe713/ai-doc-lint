"""findings 查询/状态处理/归属隔离 + 文档列表接口测试。"""

import uuid

from app.models.document import CheckFinding, Document
from conftest import TestSessionLocal
from tests.test_intake import _auth, _make_user, _token


def _upload_doc(client, headers, name="report.txt", content=b"hello"):
    resp = client.post(
        "/api/v1/documents/upload",
        files={"files": (name, content, "text/plain")},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    item = resp.json()["tasks"][0]
    return item["document_id"]


def _add_finding(document_id, user_id, *, checker="format", rule_id="format.page.size",
                 severity="warning", message="问题"):
    db = TestSessionLocal()
    try:
        finding = CheckFinding(
            document_id=uuid.UUID(document_id), user_id=user_id,
            checker=checker, rule_id=rule_id, severity=severity,
            message=message, status="open",
        )
        db.add(finding)
        db.commit()
        return finding.id
    finally:
        db.close()


def _user_id(username):
    db = TestSessionLocal()
    try:
        from app.models.user import User
        return db.query(User).filter(User.username == username).one().id
    finally:
        db.close()


def test_list_and_filter_findings(client, monkeypatch):
    monkeypatch.setattr("app.api.documents.enqueue_parse", lambda task_id: None)
    headers = _auth(client, "find_owner")
    uid = _user_id("find_owner")
    doc_id = _upload_doc(client, headers)
    _add_finding(doc_id, uid, checker="format", severity="warning", message="纸张问题")
    _add_finding(doc_id, uid, checker="typo", severity="warning", message="错别字问题")
    _add_finding(doc_id, uid, checker="format", rule_id="format.font.body",
                 severity="info", message="字体问题")

    resp = client.get(f"/api/v1/documents/{doc_id}/findings", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 3

    resp = client.get(
        f"/api/v1/documents/{doc_id}/findings?checker=typo", headers=headers
    )
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["checker"] == "typo"

    resp = client.get(
        f"/api/v1/documents/{doc_id}/findings?severity=info", headers=headers
    )
    assert resp.json()["total"] == 1


def test_patch_finding_status(client, monkeypatch):
    monkeypatch.setattr("app.api.documents.enqueue_parse", lambda task_id: None)
    headers = _auth(client, "find_patch")
    uid = _user_id("find_patch")
    doc_id = _upload_doc(client, headers)
    fid = _add_finding(doc_id, uid)

    resp = client.patch(f"/api/v1/findings/{fid}", headers=headers,
                        json={"status": "ignored"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"

    resp = client.patch(f"/api/v1/findings/{fid}", headers=headers,
                        json={"status": "fixed"})
    assert resp.json()["status"] == "fixed"

    bad = client.patch(f"/api/v1/findings/{fid}", headers=headers,
                       json={"status": "nope"})
    assert bad.status_code == 422


def test_findings_ownership_isolation(client, monkeypatch):
    monkeypatch.setattr("app.api.documents.enqueue_parse", lambda task_id: None)
    owner_headers = _auth(client, "find_owner2")
    owner_uid = _user_id("find_owner2")
    doc_id = _upload_doc(client, owner_headers)
    fid = _add_finding(doc_id, owner_uid)

    _make_user("find_other")
    other_headers = {"Authorization": f"Bearer {_token(client, 'find_other')}"}

    resp = client.get(f"/api/v1/documents/{doc_id}/findings", headers=other_headers)
    assert resp.status_code == 404
    resp = client.patch(f"/api/v1/findings/{fid}", headers=other_headers,
                        json={"status": "ignored"})
    assert resp.status_code == 404


def test_list_documents(client, monkeypatch):
    monkeypatch.setattr("app.api.documents.enqueue_parse", lambda task_id: None)
    headers = _auth(client, "find_lister")
    _upload_doc(client, headers, name="one.txt")
    _upload_doc(client, headers, name="two.txt")

    resp = client.get("/api/v1/documents", headers=headers)
    assert resp.status_code == 200
    names = {d["filename"] for d in resp.json()}
    assert {"one.txt", "two.txt"} <= names
