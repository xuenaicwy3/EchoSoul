import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List
from sqlalchemy import select
from app.database import get_async_session
from app.models.db_models import LifeLog, UserOfflineSettings
from app.redis_client import get_redis_client
from app.websocket_manager import manager
from app.config import Settings
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)

class OfflineService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.llm = init_chat_model(
            model=settings.LLM_MODEL,
            model_provider="openai",
            temperature=0.8,
            max_tokens=300,
            api_key=settings.DASHSCOPE_API_KEY,
            base_url=settings.DASHSCOPE_BASE_URL,
        )

    # ---------- 生活日志生成 ----------
    async def generate_life_log(self, user_id: str, role_type: str,
                                chat_history_text: str, facts_text: str) -> str:
        """生成一篇生活日志，返回内容"""
        prompt = f"""你是一个虚拟伴侣角色，请根据以下信息，写一篇日记或给用户的留言（200字以内）。语气要温柔、亲切，符合角色特点。

        用户与你最近聊天记录摘要：
        {chat_history_text[:500]}
        
        你对用户的了解：
        {facts_text}
        
        请直接写出这篇日志，不要包含任何说明文字。"""

        messages = [HumanMessage(content=prompt)]
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, self.llm.invoke, messages)
        content = response.content.strip()
        logger.info(f"生成生活日志: user={user_id[:8]}, role={role_type}")
        return content

    async def save_life_log(self, user_id: str, role_type: str, content: str, log_type: str = "daily"):
        session = get_async_session()
        async with session() as s:
            log = LifeLog(user_id=user_id, role_type=role_type, content=content, log_type=log_type)
            s.add(log)
            await s.commit()

    async def get_life_logs(self, user_id: str, role_type: str, limit: int = 5) -> list:
        session = get_async_session()
        async with session() as s:
            result = await s.execute(
                select(LifeLog)
                .where(LifeLog.user_id == user_id, LifeLog.role_type == role_type)
                .order_by(LifeLog.created_at.desc())
                .limit(limit)
            )
            logs = result.scalars().all()
            return [{"content": log.content, "time": log.created_at.isoformat(), "type": log.log_type} for log in logs]

    # ---------- 用户设置 ----------
    async def get_settings(self, user_id: str, role_type: str) -> Dict:
        session = get_async_session()
        async with session() as s:
            result = await s.execute(
                select(UserOfflineSettings).where(
                    UserOfflineSettings.user_id == user_id,
                    UserOfflineSettings.role_type == role_type
                )
            )
            settings = result.scalar_one_or_none()
            if not settings:
                return {"life_log_enabled": True, "companion_enabled": False, "companion_start": None, "companion_end": None}
            return {
                "life_log_enabled": settings.life_log_enabled,
                "companion_enabled": settings.companion_enabled,
                "companion_start": settings.companion_start,
                "companion_end": settings.companion_end,
            }

    async def update_settings(self, user_id: str, role_type: str, data: dict):
        session = get_async_session()
        async with session() as s:
            result = await s.execute(
                select(UserOfflineSettings).where(
                    UserOfflineSettings.user_id == user_id,
                    UserOfflineSettings.role_type == role_type
                )
            )
            settings = result.scalar_one_or_none()
            if settings:
                for k, v in data.items():
                    setattr(settings, k, v)
            else:
                settings = UserOfflineSettings(user_id=user_id, role_type=role_type, **data)
                s.add(settings)
            await s.commit()

    # ---------- 消息推送 ----------
    async def push_message_to_user(self, user_id: str, role_type: str, message: str, use_ws: bool = True):
        """将消息推送到用户的 Redis 队列，并可选择通过 WebSocket 实时推送"""
        # Redis 队列（离线消息）
        r = get_redis_client()
        await r.rpush(f"user:pending_messages:{user_id}", message)

        # WebSocket 实时推送
        if use_ws and self.settings.USE_WEBSOCKET:
            await manager.send_personal_message(user_id, {
                "type": "life_log",
                "content": message
            })