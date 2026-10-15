"""W8: 可观测性 - Prometheus 文本指标 + 系统健康统计。

/health 是依赖探活（给编排用）；/metrics 是聚合指标（给监控抓取，无认证、不含文档内容）；
/admin/system/stats 是管理员可读的系统健康页数据。
"""

import time

from fastapi import APIRouter, Request
from sqlalchemy import func, select

from app.core.ratelimit import get_redis
from app.db.session import SessionLocal
from app.models.document import Document, DocumentTask

# ---- 进程内聚合（模块级，仅计数，无文档内容） ----
_HTTP = {
    "requests_total": 0,
    "by_status": {},   # {status: count}
    "by_route": {},    # {route_prefix: count}
    "latency_sum": 0.0,
    "latency_count": 0,
}

CELERY_QUEUES = ["parse", "review", "annotate", "learn", "cross_compare", "embed"]

TASK_STATES = [
    "pending", "running", "retrying", "awaiting_decision", "parsed", "failed", "cancelled",
]

router = APIRouter(tags=["monitoring"])


def _safe_prefix(path: str) -> str:
    if path.startswith("/api/v1/"):
        seg = path[len("/api/v1/"):].split("/", 1)[0]
        return f"/api/v1/{seg}"
    return path.split("?")[0]


def install_metrics(app) -> None:
    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start
        prefix = _safe_prefix(request.url.path)
        _HTTP["requests_total"] += 1
        _HTTP["by_status"][response.status_code] = _HTTP["by_status"].get(response.status_code, 0) + 1
        _HTTP["by_route"][prefix] = _HTTP["by_route"].get(prefix, 0) + 1
        _HTTP["latency_sum"] += elapsed
        _HTTP["latency_count"] += 1
        return response


def _db_stats() -> dict:
    out: dict[str, object] = {}
    try:
        with SessionLocal() as db:
            out["documents"] = db.execute(select(func.count(Document.id))).scalar_one()
            out["tasks_total"] = db.execute(select(func.count(DocumentTask.id))).scalar_one()
            out["tasks_by_state"] = {
                st: db.execute(
                    select(func.count(DocumentTask.id)).where(DocumentTask.status == st)
                ).scalar_one()
                for st in TASK_STATES
            }
        out["db"] = "ok"
    except Exception as exc:  # noqa: BLE001
        out["db"] = f"error: {type(exc).__name__}"
    return out


def _queue_lengths() -> dict:
    out: dict[str, int | str] = {}
    try:
        r = get_redis()
        for q in CELERY_QUEUES:
            out[q] = r.llen(q)
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}"
    return out


def _metrics_text() -> str:
    lines = [
        "# HELP aidoc_http_requests_total HTTP 请求总数（按状态码/路由前缀分桶）",
        "# TYPE aidoc_http_requests_total counter",
    ]
    for status, cnt in sorted(_HTTP["by_status"].items()):
        lines.append(f'aidoc_http_requests_total{{status="{status}"}} {cnt}')
    lines.append("# HELP aidoc_http_request_latency_seconds 请求延迟（累计秒）")
    lines.append("# TYPE aidoc_http_request_latency_seconds summary")
    lines.append(f"aidoc_http_request_latency_seconds_sum {_HTTP['latency_sum']:.6f}")
    lines.append(f"aidoc_http_request_latency_seconds_count {_HTTP['latency_count']}")
    db = _db_stats()
    lines.append("# HELP aidoc_documents_total 文档总数")
    lines.append("# TYPE aidoc_documents_total gauge")
    lines.append(f"aidoc_documents_total {db.get('documents', 0)}")
    if isinstance(db.get("tasks_by_state"), dict):
        lines.append("# HELP aidoc_tasks_by_state 任务状态分布")
        lines.append("# TYPE aidoc_tasks_by_state gauge")
        for st, cnt in db["tasks_by_state"].items():
            lines.append(f'aidoc_tasks_by_state{{state="{st}"}} {cnt}')
    ql = _queue_lengths()
    lines.append("# HELP aidoc_celery_queue_depth Celery 队列深度")
    lines.append("# TYPE aidoc_celery_queue_depth gauge")
    for q, depth in ql.items():
        if q == "error":
            continue
        lines.append(f'aidoc_celery_queue_depth{{queue="{q}"}} {depth}')
    return "\n".join(lines) + "\n"


@router.get("/metrics")
def metrics() -> dict:
    """Prometheus 文本格式指标（仅聚合计数，无文档内容，可匿名抓取）。"""
    from fastapi.responses import PlainTextResponse

    return PlainTextResponse(_metrics_text(), media_type="text/plain; version=0.0.4")
