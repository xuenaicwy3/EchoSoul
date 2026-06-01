import logging
from typing import List, Dict
from datetime import datetime
from sqlalchemy import select, delete
from app.database import get_async_session
from app.models.db_models import ChatHistory as ChatHistoryModel


logger = logging.getLogger(__name__)

class ChatHistoryManager:
    @classmethod
    async def add_message(self, user_id: str, role_type: str, sender: str, message: str):
        async_session = get_async_session()
        async with async_session() as session:
            async with session.begin():
                record = ChatHistoryModel(
                    user_id=user_id, role_type=role_type,
                    sender=sender, message=message,
                    timestamp=datetime.utcnow()
                )
                session.add(record)
            logger.debug("历史消息已存储: sender=%s, role=%s", sender, role_type)

    @classmethod
    async def get_history(self, user_id: str, role_type: str, limit: int = 100) -> List[Dict]:
        async_session = get_async_session()
        async with async_session() as session:
            result = await session.execute(
                select(ChatHistoryModel)
                .where(
                    ChatHistoryModel.user_id == user_id,
                    ChatHistoryModel.role_type == role_type
                )
                .order_by(ChatHistoryModel.timestamp.asc())
                .limit(limit)
            )
            rows = result.scalars().all()
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