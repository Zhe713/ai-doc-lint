"""WebSocket 鉴权：非法 token 收到错误后以 1008 关闭。"""

import pytest
from starlette.websockets import WebSocketDisconnect


def test_ws_rejects_bad_token(client):
    with client.websocket_connect("/api/v1/ws?token=not-a-jwt") as ws:
        msg = ws.receive_json()
        assert msg["error"] == "unauthorized"
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == 1008


def test_ws_rejects_missing_token(client):
    with client.websocket_connect("/api/v1/ws") as ws:
        msg = ws.receive_json()
        assert msg["error"] == "unauthorized"
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == 1008
