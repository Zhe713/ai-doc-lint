"""安全回归：跨用户越权（IDOR）与规则包归属隔离。

锁住两处高危：
1. 版本 diff 接口不能读取他人文档原文（BOLA）；
2. 规则包列表/详情不能泄露他人私有规则内容。
"""

from app.core.security import hash_password
from app.models.document import Artifact, Document
from app.models.rules import RulePack
from app.models.user import User, UserRole
from app.services.setup_service import ensure_roles
from conftest import TestSessionLocal
from tests.test_intake import _make_user, _token


def _make_doc(username: str, filename: str = "doc.txt", text: str = "hello contract"):
    db = TestSessionLocal()
    try:
        user = db.query(User).filter(User.username == username).one()
        doc = Document(
            user_id=user.id, filename=filename,
            storage_key=f"test/{filename}", sha256=hash_password(filename)[:64],
            size_bytes=len(text), ext="txt", doc_type="contract",
        )
        db.add(doc)
        db.flush()
        db.add(Artifact(
            document_id=doc.id, task_id=None, kind="plaintext",
            storage_key=f"test/{filename}.plain", content_type="text/plain",
            size_bytes=len(text),
        ))
        db.commit()
        return str(doc.id)
    finally:
        db.close()


def test_diff_cannot_read_others_document(client, monkeypatch):
    """普通用户不能通过 /compare/diff 读取他人文档原文。"""
    _make_user("sec_owner")
    _make_user("sec_attacker")
    owner_token = _token(client, "sec_owner")
    attacker_token = _token(client, "sec_attacker")

    doc_a = _make_doc("sec_owner", "a.txt", "甲方秘密合同正文")
    doc_b = _make_doc("sec_owner", "b.txt", "乙方版本正文")

    # 打桩 storage：测试库无 MinIO，返回假正文即可（越权判定在取文本之前）
    def fake_get(key):
        return b"fake plaintext"
    monkeypatch.setattr("app.db.storage.get_object_bytes", fake_get)

    # 攻击者访问他人文档 → 404（不能泄露是否存在，更不能给原文）
    resp = client.get(
        "/api/v1/compare/diff",
        params={"doc_a_id": doc_a, "doc_b_id": doc_b},
        headers={"Authorization": f"Bearer {attacker_token}"},
    )
    assert resp.status_code == 404, resp.text

    # 文档主人自己能访问（200 或 409 未解析，但绝不能是 404 越权）
    resp = client.get(
        "/api/v1/compare/diff",
        params={"doc_a_id": doc_a, "doc_b_id": doc_b},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp.status_code != 404, resp.text


def test_rule_packs_are_scoped_to_owner(client):
    """非管理员只能看到/读取自己创建的规则包。"""
    _make_user("sec_pack_owner")
    _make_user("sec_pack_other")
    owner_token = _token(client, "sec_pack_owner")
    other_token = _token(client, "sec_pack_other")

    # owner 建一个私有规则包
    resp = client.post(
        "/api/v1/rules/packs",
        json={
            "name": "我的私有条款包",
            "pack_type": "clause",
            "doc_type": "contract",
            "yaml_content": '{"version":1,"clauses":[{"id":"c1","name":"付款","strong":["付款"],"weak":[],"severity":"warning"}]}',
        },
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp.status_code == 201, resp.text
    pack_id = resp.json()["id"]

    # other 列出规则包 → 看不到 owner 的包
    resp = client.get("/api/v1/rules/packs", headers={"Authorization": f"Bearer {other_token}"})
    assert resp.status_code == 200
    assert all(p["id"] != pack_id for p in resp.json()), "非管理员不应枚举他人规则包"

    # other 直接读详情 → 404
    resp = client.get(f"/api/v1/rules/packs/{pack_id}",
                      headers={"Authorization": f"Bearer {other_token}"})
    assert resp.status_code == 404, resp.text

    # other 尝试编辑/删除 → 403
    resp = client.put(
        f"/api/v1/rules/packs/{pack_id}",
        json={"name": "篡改"},
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert resp.status_code == 403, resp.text
    resp = client.delete(
        f"/api/v1/rules/packs/{pack_id}",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert resp.status_code == 403, resp.text

    # owner 自己能编辑自己的包（不再只能管理员才能改自己的规则）
    resp = client.put(
        f"/api/v1/rules/packs/{pack_id}",
        json={"name": "改个名字"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp.status_code == 200, resp.text
