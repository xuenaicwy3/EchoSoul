"""
聊天历史 (ChatHistory) Repository。
"""
import logging
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import select, func, desc

from app.infrastructure.repositories.base import BaseRepository
from app.models.db_models import ChatHistory

logger = logging.getLogger(__name__)


class ChatHistoryRepository(BaseRepository[ChatHistory]):
    model_class = ChatHistory

    async def find_by_user_role(
        self,
        user_id: str,
        role_type: str,
        limit: int = 50,
        before: Optional[datetime] = None,
    ) -> Sequence[ChatHistory]:
        """获取指定用户-角色的聊天历史，按时间倒序。"""
        stmt = (
            select(ChatHistory)
            .where(
                ChatHistory.user_id == user_id,
                ChatHistory.role_type == role_type,
            )
            .order_by(desc(ChatHistory.timestamp))
            .limit(limit)
        )
        if before:
            stmt = stmt.where(ChatHistory.timestamp < before)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count_rounds(self, user_id: str, role_type: str) -> int:
        """统计对话轮数（user 消息数）。"""
        result = await self.session.execute(
            select(func.count())
            .select_from(ChatHistory)
            .where(
                ChatHistory.user_id == user_id,
                ChatHistory.role_type == role_type,
            )
        )
        return result.scalar() or 0

    async def delete_by_user_role(self, user_id: str, role_type: str) -> int:
        """删除指定用户-角色的全部聊天历史。返回删除行数。"""
        from sqlalchemy import delete
        result = await self.session.execute(
            delete(ChatHistory).where(
                ChatHistory.user_id == user_id,
                ChatHistory.role_type == role_type,
            )
        )
        await self.session.flush()
        return result.rowcount

    async def get_distinct_roles(self, user_id: str) -> list[str]:
        """获取用户聊过的所有角色类型。"""
        result = await self.session.execute(
            select(ChatHistory.role_type)
            .where(ChatHistory.user_id == user_id)
            .distinct()
        )
        return [row[0] for row in result.fetchall()]
