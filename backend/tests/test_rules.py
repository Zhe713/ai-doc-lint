"""W6 Day26：规则包管理 API + loader DB 优先路径。"""

import pytest
from fastapi.testclient import TestClient

from app.checkers import loader
from app.checkers.loader import (
    invalidate_pack_caches,
    load_clause_pack,
    load_cross_rules,
    load_field_pack,
)
from conftest import TestSessionLocal
from tests.test_intake import _make_user, _token

VALID_CLAUSE = """version: 1
clauses:
  - id: payment_terms
    name: 付款条款
    strong:
      - 付款
    weak:
      - 支付
"""

INVALID_CLAUSE = """version: 1
clauses:
  - id: payment_terms
    name: 付款条款
"""

VALID_FIELD = """version: 1
fields:
  - key: party_a
    label: 甲方
    type: string
    patterns:
      - 甲方
"""


def _login(client: TestClient) -> str:
    db = TestSessionLocal()
    try:
        from app.models.user import User
        exists = db.query(User).filter(User.username == "rules_admin").first()
    finally:
        db.close()
    if exists is None:
        _make_user("rules_admin", admin=True)
    return _token(client, "rules_admin")


@pytest.fixture(autouse=True)
def _use_test_db_session(monkeypatch):
    """loader 的 DB 查询走测试库会话；每测试前清空 rule_packs 防互相污染。"""
    monkeypatch.setattr(loader, "_SESSION_FACTORY", TestSessionLocal)
    db = TestSessionLocal()
    try:
        from app.models.rules import RulePack
        db.query(RulePack).delete()
        db.commit()
    finally:
        db.close()
    yield
    invalidate_pack_caches()


def test_upload_valid_clause_pack(client):
    h = {"Authorization": f"Bearer {_login(client)}"}
    r = client.post("/api/v1/rules/packs", json={
        "name": "自定义付款条款包",
        "pack_type": "clause",
        "doc_type": "contract",
        "yaml_content": VALID_CLAUSE,
    }, headers=h)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["source"] == "custom"
    assert body["enabled"] is True


def test_upload_invalid_pack_rejected(client):
    h = {"Authorization": f"Bearer {_login(client)}"}
    r = client.post("/api/v1/rules/packs", json={
        "name": "非法条款包",
        "pack_type": "clause",
        "doc_type": "contract",
        "yaml_content": INVALID_CLAUSE,
    }, headers=h)
    assert r.status_code == 422
    assert "校验失败" in r.json()["detail"]


def test_builtin_packs_listed(client):
    h = {"Authorization": f"Bearer {_login(client)}"}
    r = client.get("/api/v1/rules/packs/builtin", headers=h)
    assert r.status_code == 200
    types = {p["pack_type"] for p in r.json()}
    assert types == {"format", "clause", "field", "cross"}


def test_toggle_pack(client):
    h = {"Authorization": f"Bearer {_login(client)}"}
    r = client.post("/api/v1/rules/packs", json={
        "name": "待停用条款包",
        "pack_type": "clause",
        "doc_type": "contract",
        "yaml_content": VALID_CLAUSE,
    }, headers=h)
    pack_id = r.json()["id"]
    r = client.patch(f"/api/v1/rules/packs/{pack_id}/toggle",
                     json={"enabled": False}, headers=h)
    assert r.status_code == 200
    assert r.json()["enabled"] is False


def test_loader_prefers_custom_pack(client, monkeypatch):
    """启用自定义 clause 包后，load_clause_pack 返回自定义内容而非内置。"""
    h = {"Authorization": f"Bearer {_login(client)}"}
    r = client.post("/api/v1/rules/packs", json={
        "name": "自定义付款条款包",
        "pack_type": "clause",
        "doc_type": "contract",
        "yaml_content": VALID_CLAUSE,
    }, headers=h)
    assert r.status_code == 201

    invalidate_pack_caches()
    clauses = load_clause_pack("contract")
    assert clauses == [{
        "id": "payment_terms", "name": "付款条款",
        "strong": ["付款"], "weak": ["支付"],
    }]


def test_loader_falls_back_when_disabled(client):
    """停用自定义包后回落内置包。"""
    h = {"Authorization": f"Bearer {_login(client)}"}
    r = client.post("/api/v1/rules/packs", json={
        "name": "自定义付款条款包",
        "pack_type": "clause",
        "doc_type": "contract",
        "yaml_content": VALID_CLAUSE,
    }, headers=h)
    pack_id = r.json()["id"]
    client.patch(f"/api/v1/rules/packs/{pack_id}/toggle",
                 json={"enabled": False}, headers=h)

    invalidate_pack_caches()
    clauses = load_clause_pack("contract")
    assert all(c["id"] != "payment_terms" for c in clauses)


def test_loader_field_pack_custom(client):
    h = {"Authorization": f"Bearer {_login(client)}"}
    r = client.post("/api/v1/rules/packs", json={
        "name": "自定义字段包",
        "pack_type": "field",
        "doc_type": "contract",
        "yaml_content": VALID_FIELD,
    }, headers=h)
    assert r.status_code == 201
    invalidate_pack_caches()
    fields = load_field_pack("contract")
    assert fields == [{
        "key": "party_a", "label": "甲方", "type": "string",
        "patterns": ["甲方"],
    }]


def test_delete_pack(client):
    h = {"Authorization": f"Bearer {_login(client)}"}
    r = client.post("/api/v1/rules/packs", json={
        "name": "待删除条款包",
        "pack_type": "clause",
        "doc_type": "contract",
        "yaml_content": VALID_CLAUSE,
    }, headers=h)
    pack_id = r.json()["id"]
    r = client.delete(f"/api/v1/rules/packs/{pack_id}", headers=h)
    assert r.status_code == 204
    r = client.get(f"/api/v1/rules/packs/{pack_id}", headers=h)
    assert r.status_code == 404


def test_cross_pack_still_loads_builtin():
    """未上传 cross 自定义包时，内置 cross 规则正常加载。"""
    rules = load_cross_rules("contract")
    assert rules is not None
    assert "checks" in rules
