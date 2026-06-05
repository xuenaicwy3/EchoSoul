from fastapi import WebSocket
from typing import Dict
import asyncio
import json
import logging

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        # 存储格式：{ user_id: WebSocket }
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, user_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        logger.info(f"WebSocket 连接: user={user_id[:8]}, 当前连接数={len(self.active_connections)}")

    def disconnect(self, user_id: str):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
            logger.info(f"WebSocket 断开: user={user_id[:8]}, 当前连接数={len(self.active_connections)}")

    async def send_personal_message(self, user_id: str, message: dict):
        """向指定用户发送 JSON 消息"""
        ws = self.active_connections.get(user_id)
        if ws:
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.error(f"WebSocket 发送失败: {e}")
                self.disconnect(user_id)

    async def broadcast(self, message: dict):
        """向所有在线用户广播消息"""
        for user_id, ws in self.active_connections.items():
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.error(f"广播到 {user_id[:8]} 失败: {e}")
                self.disconnect(user_id)

manager = ConnectionManager()