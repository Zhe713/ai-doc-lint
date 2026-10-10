"""v1 API 路由聚合。"""

from fastapi import APIRouter

from app.api import (
    admin,
    annotate,
    auth,
    chat,
    compare,
    documents,
    findings,
    health,
    setup,
    users,
    ws,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(setup.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(admin.router)
api_router.include_router(documents.router)
api_router.include_router(compare.router)
api_router.include_router(findings.router)
api_router.include_router(annotate.router)
api_router.include_router(chat.router)
api_router.include_router(ws.router)
