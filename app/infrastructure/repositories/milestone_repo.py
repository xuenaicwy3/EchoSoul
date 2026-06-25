"""
关系层 (RelationshipMilestone) Repository。
"""
import logging
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import select, func, desc

from app.infrastructure.repositories.base import BaseRepository
from app.models.db_models import RelationshipMilestone

logger = logging.getLogger(__name__)


class MilestoneRepository(BaseRepository[RelationshipMilestone]):
    model_class = RelationshipMilestone

    async def find_active(
        self, user_id: str, role_type: str
    ) -> Sequence[RelationshipMilestone]:
        """获取所有活跃里程碑，按时间倒序。"""
        result = await self.session.execute(
            select(RelationshipMilestone)
            .where(
                RelationshipMilestone.user_id == user_id,
                RelationshipMilestone.role_type == role_type,
                RelationshipMilestone.status == "active",
            )
            .order_by(desc(RelationshipMilestone.created_at))
        )
        return result.scalars().all()

    async def find_by_event_type(
        self, user_id: str, role_type: str, event_type: str
    ) -> Optional[RelationshipMilestone]:
        """按事件类型查找里程碑（不限 status）。"""
        result = await self.session.execute(
            select(RelationshipMilestone).where(
                RelationshipMilestone.user_id == user_id,
                RelationshipMilestone.role_type == role_type,
                RelationshipMilestone.event_type == event_type,
            )
        )
        return result.scalar_one_or_none()

    async def find_archived_thresholds(
        self, user_id: str, role_type: str
    ) -> Sequence[RelationshipMilestone]:
        """查找归档的亲密度阈值里程碑。"""
        result = await self.session.execute(
            select(RelationshipMilestone).where(
                RelationshipMilestone.user_id == user_id,
                RelationshipMilestone.role_type == role_type,
                RelationshipMilestone.status == "archived",
                RelationshipMilestone.event_type.in_([
                    "intimacy_30", "intimacy_50", "intimacy_80"
                ]),
            )
        )
        return result.scalars().all()

    async def find_all_for_user(
        self, user_id: str, role_type: str
    ) -> Sequence[RelationshipMilestone]:
        """获取用户-角色的全部里程碑（含 active 和 archived）。"""
        result = await self.session.execute(
            select(RelationshipMilestone).where(
                RelationshipMilestone.user_id == user_id,
                RelationshipMilestone.role_type == role_type,
            )
        )
        return result.scalars().all()

    async def count_active(self, user_id: str, role_type: str) -> int:
        """统计活跃里程碑数。"""
        result = await self.session.execute(
            select(func.count()).select_from(RelationshipMilestone).where(
                RelationshipMilestone.user_id == user_id,
                RelationshipMilestone.role_type == role_type,
                RelationshipMilestone.status == "active",
            )
        )
        return result.scalar() or 0
