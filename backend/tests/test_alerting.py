"""W9-2: 监控告警测试 - 阈值判定、去重入库、API 查询。"""

from sqlalchemy import select

from app.models.alert import ALERT_STATUS_ACTIVE, AlertEvent
from app.tasks.alerting import evaluate
from conftest import TestSessionLocal


def test_evaluate_queue_backlog_and_failure():
    alerts = evaluate({"parse": 99, "review": 1}, failure_rate=0.5, stalled=0)
    types = {a["alert_type"] for a in alerts}
    assert "queue_backlog" in types
    assert "parse_failure" in types
    assert all(a["level"] in ("warning", "critical") for a in alerts)
    assert "stalled" not in types


def test_evaluate_stalled():
    alerts = evaluate({"parse": 1}, failure_rate=0.0, stalled=3)
    assert any(a["alert_type"] == "task_stalled" for a in alerts)


def test_evaluate_clean():
    alerts = evaluate({"parse": 1, "review": 2}, failure_rate=0.0, stalled=0)
    assert alerts == []


def test_check_system_alerts_writes_and_dedups(client):
    from app.tasks import alerting as alerting_mod

    # 让任务函数使用测试库会话
    alerting_mod.SessionLocal = TestSessionLocal
    # 注入：队列积压（Valkey 塞入超过阈值的项），其余指标正常
    from app.core.ratelimit import get_redis

    r = get_redis()
    for _ in range(60):
        r.lpush("parse", "x")
    try:
        # 首次巡检：写入告警
        result = alerting_mod.check_system_alerts()
        assert result["written"] >= 1
        # 去重：再次巡检不重复写
        result2 = alerting_mod.check_system_alerts()
        db = TestSessionLocal()
        try:
            open_rows = db.execute(
                select(AlertEvent).where(AlertEvent.status == ALERT_STATUS_ACTIVE)
            ).scalars().all()
            queue_alerts = [x for x in open_rows if x.alert_type == "queue_backlog"]
            assert len(queue_alerts) == 1
        finally:
            db.close()
        # API 查询（管理员）
        from tests.test_intake import _make_user, _token

        _make_user("alert_admin", admin=True)
        token = _token(client, "alert_admin")
        resp = client.get(
            "/api/v1/admin/alerts",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert any(i["alert_type"] == "queue_backlog" for i in body["items"])
    finally:
        # 清理测试用队列数据
        try:
            from app.core.ratelimit import get_redis as gr

            rr = gr()
            for _ in range(60):
                rr.rpop("parse")
        except Exception:  # noqa: BLE001
            pass
