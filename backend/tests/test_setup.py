def test_setup_status_when_no_admin(client):
    # 测试库可能被其他用例初始化；这里仅校验返回结构
    resp = client.get("/api/v1/setup/status")
    assert resp.status_code == 200
    assert "needs_setup" in resp.json()
    assert "open_registration" in resp.json()


def test_setup_admin_once(client):
    """全新测试库语义：首个管理员只能创建一次（已初始化则 409）。"""
    status = client.get("/api/v1/setup/status").json()
    resp = client.post(
        "/api/v1/setup/admin", json={"username": "rootadmin", "password": "SuperSecret123"}
    )
    if status["needs_setup"]:
        assert resp.status_code == 201, resp.text
        assert "admin" in resp.json()["roles"]
        # 再次初始化必须拒绝
        resp2 = client.post(
            "/api/v1/setup/admin", json={"username": "rootadmin2", "password": "SuperSecret123"}
        )
        assert resp2.status_code == 409
        assert client.get("/api/v1/setup/status").json()["needs_setup"] is False
    else:
        assert resp.status_code == 409


def test_setup_admin_validation(client):
    resp = client.post("/api/v1/setup/admin", json={"username": "ab", "password": "123"})
    assert resp.status_code == 422
