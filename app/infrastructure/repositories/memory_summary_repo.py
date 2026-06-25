"""
记忆摘要 (UserMemorySummary) Repository。
"""
import logging
from typing import Optional

from sqlalchemy import select, desc

from app.infrastructure.repositories.base import BaseRepository
from app.models.db_models import UserMemorySummary

logger = logging.getLogger(__name__)


class MemorySummaryRepository(BaseRepository[UserMemorySummary]):
    model_class = UserMemorySummary

    async def find_latest(
        self, user_id: str, role_type: str
    ) -> Optional[UserMemorySummary]:
        """获取最新的记忆摘要缓存。"""
        result = await self.session.execute(
            select(UserMemorySummary)
            .where(
                UserMemorySummary.user_id == user_id,
                UserMemorySummary.role_type == role_type,
            )
            .order_by(desc(UserMemorySummary.updated_at))
            .limit(1)
        )
        return result.scalar_one_or_none()
