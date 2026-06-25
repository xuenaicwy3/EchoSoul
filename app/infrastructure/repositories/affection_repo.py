"""
好感度 (Affection) Repository。
"""
import logging
from typing import Optional, Sequence

from sqlalchemy import select

from app.infrastructure.repositories.base import BaseRepository
from app.models.db_models import Affection

logger = logging.getLogger(__name__)


class AffectionRepository(BaseRepository[Affection]):
    model_class = Affection

    async def find_by_user_role(
        self, user_id: str, role_type: str
    ) -> Optional[Affection]:
        """获取用户-角色的好感度记录。"""
        result = await self.session.execute(
            select(Affection).where(
                Affection.user_id == user_id,
                Affection.role_type == role_type,
            )
        )
        return result.scalar_one_or_none()

    async def find_or_create(
        self, user_id: str, role_type: str
    ) -> Affection:
        """获取或创建好感度记录（初始值均为 10）。"""
        aff = await self.find_by_user_role(user_id, role_type)
        if aff is None:
            aff = Affection(
                user_id=user_id,
                role_type=role_type,
                intimacy=10.0,
                trust=10.0,
                fun=10.0,
                growth=10.0,
            )
            self.session.add(aff)
            await self.session.flush()
        return aff

    async def find_all_stale(
        self, days: int = 7
    ) -> Sequence[Affection]:
        """查找超过 N 天未互动的好感度记录（用于衰减）。"""
        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self.session.execute(
            select(Affection).where(
                Affection.last_interaction < cutoff
            )
        )
        return result.scalars().all()
