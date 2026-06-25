"""
事实层 (UserFact) Repository。

封装所有 UserFact 相关的数据库操作。
"""
import logging
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import select, func, update

from app.infrastructure.repositories.base import BaseRepository
from app.models.db_models import UserFact

logger = logging.getLogger(__name__)


class FactRepository(BaseRepository[UserFact]):
    model_class = UserFact

    async def find_active(
        self, user_id: str, role_type: str
    ) -> Sequence[UserFact]:
        """获取所有活跃事实，按 key 排序。"""
        result = await self.session.execute(
            select(UserFact)
            .where(
                UserFact.user_id == user_id,
                UserFact.role_type == role_type,
                UserFact.status == "active",
            )
            .order_by(UserFact.key)
        )
        return result.scalars().all()

    async def find_by_key(
        self, user_id: str, role_type: str, key: str, status: str = "active"
    ) -> Optional[UserFact]:
        """按 key 查找指定状态的事实。"""
        result = await self.session.execute(
            select(UserFact).where(
                UserFact.user_id == user_id,
                UserFact.role_type == role_type,
                UserFact.key == key,
                UserFact.status == status,
            )
        )
        return result.scalar_one_or_none()

    async def find_archived_by_key(
        self, user_id: str, role_type: str, key: str
    ) -> Optional[UserFact]:
        """查找归档状态的事实。"""
        return await self.find_by_key(user_id, role_type, key, status="archived")

    async def count_active(self, user_id: str, role_type: str) -> int:
        """统计活跃事实数。"""
        result = await self.session.execute(
            select(func.count()).select_from(UserFact).where(
                UserFact.user_id == user_id,
                UserFact.role_type == role_type,
                UserFact.status == "active",
            )
        )
        return result.scalar() or 0

    async def find_all_active_for_user(
        self, user_id: str, role_type: str
    ) -> Sequence[UserFact]:
        """获取指定用户-角色的所有活跃事实。"""
        return await self.find_active(user_id, role_type)

    async def update_status(self, fact_id: int, status: str) -> None:
        """更新事实状态。"""
        await self.session.execute(
            update(UserFact)
            .where(UserFact.id == fact_id)
            .values(status=status)
        )
