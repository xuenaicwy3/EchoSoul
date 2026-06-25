"""
WebSocket 路由。
"""
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from app.auth import decode_access_token
from app.websocket_manager import manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str, token: str = Query(...)):
    """WebSocket 连接端点，需要 token 验证。"""
    uid = decode_access_token(token)
    if not uid or uid != user_id:
        await websocket.close(code=4001, reason="Authentication failed")
        return

    await manager.connect(user_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(user_id)
