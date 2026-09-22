"""任务进度 WebSocket：access token 走查询参数（浏览器 WS 不能带 Authorization 头）。

事件流：worker → Valkey pub/sub → 本端点按用户扇出；断线时前端自动降级轮询。
"""

import asyncio
import json
import uuid

import redis.asyncio as aioredis
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.core.security import decode_token
from app.tasks.events import EVENT_CHANNEL

router = APIRouter(tags=["ws"])


@router.websocket("/ws")
async def task_ws(websocket: WebSocket, token: str = Query(default="")):
    await websocket.accept()
    try:
        payload = decode_token(token, "access")
        user_id = uuid.UUID(payload["sub"])
    except Exception:  # noqa: BLE001
        await websocket.send_json({"error": "unauthorized"})
        await websocket.close(code=1008)
        return

    r = aioredis.Redis.from_url(settings.valkey_url)
    ps = r.pubsub()
    await ps.subscribe(EVENT_CHANNEL)
    try:
        while True:
            # 收客户端心跳/断连
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=0.5)
            except asyncio.TimeoutError:
                pass
            except WebSocketDisconnect:
                break

            msg = await ps.get_message(ignore_subscribe_messages=True, timeout=0.5)
            if msg and msg.get("type") == "message":
                data = json.loads(msg["data"])
                if str(data.get("user_id")) == str(user_id):
                    try:
                        await websocket.send_json(data)
                    except WebSocketDisconnect:
                        break
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await ps.unsubscribe(EVENT_CHANNEL)
            await ps.close()
            await r.close()
        except Exception:  # noqa: BLE001
            pass
