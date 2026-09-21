"""FastAPI 入口。"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.router import api_router
from app.core.config import settings
from app.db.storage import ensure_bucket
from app.services.setup_service import ensure_roles

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai-doc-lint")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 幂等的启动准备：角色存在、MinIO 桶存在；失败不阻断启动（/health 会暴露）
    try:
        from app.db.session import SessionLocal

        with SessionLocal() as db:
            ensure_roles(db)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ensure_roles failed (will retry via migration/health): %s", exc)
    try:
        ensure_bucket()
    except Exception as exc:  # noqa: BLE001
        logger.warning("ensure_bucket failed: %s", exc)
    yield


app = FastAPI(
    title="ai-doc-lint API",
    version="0.1.0",
    description="自托管 AI 文档校验工具（W1：认证与工程骨架）",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(api_router)


@app.get("/")
def root() -> dict:
    return {"name": "ai-doc-lint", "version": "0.1.0", "docs": "/docs", "health": "/health"}
