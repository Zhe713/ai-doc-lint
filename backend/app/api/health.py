"""健康检查：API 自身 + PostgreSQL / Valkey / MinIO 依赖连通性。"""

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.core.ratelimit import get_redis
from app.db.session import SessionLocal
from app.db.storage import minio_client
from app.core.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health(response: Response) -> dict:
    checks: dict[str, str] = {}

    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["postgres"] = f"error: {type(exc).__name__}"

    try:
        checks["valkey"] = "ok" if get_redis().ping() else "error"
    except Exception as exc:  # noqa: BLE001
        checks["valkey"] = f"error: {type(exc).__name__}"

    try:
        if not minio_client.bucket_exists(settings.minio_bucket):
            minio_client.make_bucket(settings.minio_bucket)
        checks["minio"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["minio"] = f"error: {type(exc).__name__}"

    overall_ok = all(v == "ok" for v in checks.values())
    if not overall_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if overall_ok else "degraded", "checks": checks}
