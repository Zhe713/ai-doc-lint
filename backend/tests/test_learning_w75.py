"""W7-5 反馈原因结构化 + 白名单先验证再生效 测试。"""

import uuid

from conftest import TestSessionLocal
from tests.test_intake import _make_user, _token
from tests.test_findings_api import _add_finding, _upload_doc
from app.models.document import CheckFinding
from app.tasks.learning import _verify_candidate_words


def _user_id(username):
    from app.models.user import User
    db = TestSessionLocal()
    try:
        return db.query(User).filter(User.username == username).one().id
    finally:
        db.close()


def _auth(client, username):
    _make_user(username)
    return {"Authorization": f"Bearer {_token(client, username)}"}


def _admin_headers(client, username="w75_admin"):
    _make_user(username, admin=True)
    return {"Authorization": f"Bearer {_token(client, username)}"}


def _typo_finding(document_id, user_id, wrong, *, status="open", reason=None):
    db = TestSessionLocal()
    try:
        f = CheckFinding(
            document_id=uuid.UUID(document_id), user_id=user_id,
            checker="typo", rule_id="typo.correction", severity="warning",
            message=f"疑似错别字：「{wrong}」建议改为「xxx」",
            status=status, feedback_reason=reason,
        )
        db.add(f)
        db.commit()
        return f.id
    finally:
        db.close()


def test_patch_finding_saves_feedback_cause(client, monkeypatch):
    """误报反馈带原因保存；非误报时原因清空。"""
    monkeypatch.setattr("app.api.documents.enqueue_parse", lambda task_id: None)
    headers = _auth(client, "w75_cause")
    uid = _user_id("w75_cause")
    doc_id = _upload_doc(client, headers)
    fid = _add_finding(doc_id, uid, checker="typo", message="疑似错别字：「签定」建议改为「签订」")

    # 误报 + 原因 → 保存
    resp = client.patch(f"/api/v1/findings/{fid}", headers=headers,
                        json={"status": "ignored", "feedback_reason": "false_positive",
                              "feedback_cause": "lexicon"})
    assert resp.status_code == 200
    assert resp.json()["feedback_reason"] == "false_positive"
    assert resp.json()["feedback_cause"] == "lexicon"

    # 改为已修复 → 原因清空（避免残留误导归因）
    resp = client.patch(f"/api/v1/findings/{fid}", headers=headers,
                        json={"status": "fixed", "feedback_reason": "fixed_by_user"})
    assert resp.status_code == 200
    assert resp.json()["feedback_cause"] is None


def test_learning_feedback_aggregates_causes(client, monkeypatch):
    """反馈统计返回误报原因分布。"""
    monkeypatch.setattr("app.api.documents.enqueue_parse", lambda task_id: None)
    headers = _auth(client, "w75_agg")
    uid = _user_id("w75_agg")
    doc_id = _upload_doc(client, headers)
    _typo_finding(doc_id, uid, "签定", status="open")
    db = TestSessionLocal()
    try:
        fid = db.query(CheckFinding).filter(CheckFinding.document_id == uuid.UUID(doc_id)).one().id
    finally:
        db.close()
    client.patch(f"/api/v1/findings/{fid}", headers=headers,
                 json={"status": "ignored", "feedback_reason": "false_positive",
                       "feedback_cause": "rule_strict"})

    # 管理员看板聚合
    admin_headers = _admin_headers(client, "w75_admin_agg")
    resp = client.get("/api/v1/admin/learning/feedback", headers=admin_headers)
    assert resp.status_code == 200
    items = resp.json()["items"]
    typo = [it for it in items if it["checker"] == "typo"]
    assert typo, "应聚合出 typo 规则"
    causes = typo[0].get("causes", {})
    assert causes.get("rule_strict", 0) >= 1, f"原因分布应含 rule_strict，实际 {causes}"


def test_verify_candidate_blocks_confirmed_and_open(client, monkeypatch):
    """白名单候选词两级验证：golden 集命中 / open / confirmed 记录都会拦截自动生效。"""
    monkeypatch.setattr("app.api.documents.enqueue_parse", lambda task_id: None)
    headers = _auth(client, "w75_verify")
    uid = _user_id("w75_verify")
    doc_id = _upload_doc(client, headers)

    # 词A：golden 集 l1 结果中存在的错词 → 拦截（先验证再生效）
    # 词B：存在 open 记录（未处理）→ 拦截
    _typo_finding(doc_id, uid, "由其", status="open")
    # 词C：存在 confirmed 记录 → 拦截
    _typo_finding(doc_id, uid, "审报", status="ignored", reason="confirmed")
    # 词D：仅误报记录且不在 golden → 安全
    _typo_finding(doc_id, uid, "签定", status="ignored", reason="false_positive")

    db = TestSessionLocal()
    try:
        safe, pending = _verify_candidate_words(db, {"由其", "审报", "签定"})
    finally:
        db.close()

    assert "由其" in pending, "open 记录应拦截"
    assert "审报" in pending, "confirmed 记录应拦截"
    assert "签定" not in safe, "golden 集含该词 typo 记录时不得自动生效（先验证再生效）"
    assert "由其" not in safe and "审报" not in safe
    # 与 golden/信号无冲突的词应安全通过
    db = TestSessionLocal()
    try:
        safe2, pending2 = _verify_candidate_words(db, {"无冲突测试词甲"})
    finally:
        db.close()
    assert "无冲突测试词甲" in safe2 and not pending2, "无冲突候选词应正常加入"
