def test_health_all_dependencies_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["checks"]["postgres"] == "ok"
    assert body["checks"]["valkey"] == "ok"
    assert body["checks"]["minio"] == "ok"


def test_root(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json()["name"] == "ai-doc-lint"
