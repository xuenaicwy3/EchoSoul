import logging
from typing import List, Dict
from zoneinfo import ZoneInfo
from sqlalchemy import select, delete
from app.database import get_async_session
from app.models.db_models import ChatHistory as ChatHistoryModel
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# 北京时间时区对象
BEIJING_TZ = ZoneInfo("Asia/Shanghai")


class ChatHistoryManager:
    @classmethod
    async def add_message(self, user_id: str, role_type: str, sender: str, message: str):
        async_session = get_async_session()
        async with async_session() as session:
            async with session.begin():
                record = ChatHistoryModel(
                    user_id=user_id, role_type=role_type,
                    sender=sender, message=message,
                    timestamp=datetime.now(timezone.utc)
                )
                session.add(record)
            logger.debug("历史消息已存储: sender=%s, role=%s", sender, role_type)

    @classmethod
    async def get_history(self, user_id: str, role_type: str, limit: int = 50, before: str = None) -> List[Dict]:
        async_session = get_async_session()
        async with async_session() as session:
            query = select(ChatHistoryModel).where(
                ChatHistoryModel.user_id == user_id,
                ChatHistoryModel.role_type == role_type
            )
            if before:
                before_dt = datetime.fromisoformat(before)
                query = query.where(ChatHistoryModel.timestamp < before_dt)

            query = query.order_by(ChatHistoryModel.timestamp.desc()).limit(limit)
            result = await session.execute(query)
            rows = result.scalars().all()
            rows = list(reversed(rows))

            history = [row.to_dict() for row in rows]
            logger.info("加载聊天历史: user=%s, role=%s, 共 %d 条", user_id[:8], role_type, len(history))
            return history

    @classmethod
    async def delete_history(self, user_id: str, role_type: str):
        async_session = get_async_session()
        async with async_session() as session:
            async with session.begin():
                await session.execute(
                    delete(ChatHistoryModel).where(
                        ChatHistoryModel.user_id == user_id,
                        ChatHistoryModel.role_type == role_type
                    )
                )
            logger.info("已删除聊天历史: user=%s, role=%s", user_id[:8], role_type)