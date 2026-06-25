"""
情绪层 (EmotionRecord) Repository。
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from sqlalchemy import select, func, desc

from app.infrastructure.repositories.base import BaseRepository
from app.models.db_models import EmotionRecord

logger = logging.getLogger(__name__)


class EmotionRecordRepository(BaseRepository[EmotionRecord]):
    model_class = EmotionRecord

    async def find_active(
        self, user_id: str, role_type: str, limit: int = 30
    ) -> Sequence[EmotionRecord]:
        """获取最近的活跃情绪记录，按时间倒序。"""
        result = await self.session.execute(
            select(EmotionRecord)
            .where(
                EmotionRecord.user_id == user_id,
                EmotionRecord.role_type == role_type,
                EmotionRecord.status == "active",
            )
            .order_by(desc(EmotionRecord.created_at))
            .limit(limit)
        )
        return result.scalars().all()

    async def find_recent_by_label(
        self, user_id: str, role_type: str, label: str, hours: int = 24
    ) -> Sequence[EmotionRecord]:
        """查找最近 N 小时内同标签的活跃记录。"""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        result = await self.session.execute(
            select(EmotionRecord).where(
                EmotionRecord.user_id == user_id,
                EmotionRecord.role_type == role_type,
                EmotionRecord.label == label,
                EmotionRecord.created_at >= cutoff,
                EmotionRecord.status == "active",
            )
        )
        return result.scalars().all()

    async def find_archived_recent(
        self, user_id: str, role_type: str, label: str, days: int = 7
    ) -> Sequence[EmotionRecord]:
        """查找最近 N 天内归档的同标签记录。"""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self.session.execute(
            select(EmotionRecord).where(
                EmotionRecord.user_id == user_id,
                EmotionRecord.role_type == role_type,
                EmotionRecord.label == label,
                EmotionRecord.status == "archived",
                EmotionRecord.last_reinforced >= cutoff,
            )
        )
        return result.scalars().all()

    async def find_stale_active(
        self, user_id: str, role_type: str, days: int = 90
    ) -> Sequence[EmotionRecord]:
        """查找超过 N 天未强化的活跃记录。"""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self.session.execute(
            select(EmotionRecord).where(
                EmotionRecord.user_id == user_id,
                EmotionRecord.role_type == role_type,
                EmotionRecord.last_reinforced < cutoff,
                EmotionRecord.status == "active",
            )
        )
        return result.scalars().all()

    async def count_active(self, user_id: str, role_type: str) -> int:
        """统计活跃情绪记录数。"""
        result = await self.session.execute(
            select(func.count()).select_from(EmotionRecord).where(
                EmotionRecord.user_id == user_id,
                EmotionRecord.role_type == role_type,
                EmotionRecord.status == "active",
            )
        )
        return result.scalar() or 0

    async def count_by_label(
        self, user_id: str, role_type: str, label: str
    ) -> int:
        """统计指定标签的记录数（含 active 和 archived）。"""
        result = await self.session.execute(
            select(func.count()).select_from(EmotionRecord).where(
                EmotionRecord.user_id == user_id,
                EmotionRecord.role_type == role_type,
                EmotionRecord.label == label,
                EmotionRecord.status.in_(["active", "archived"]),
            )
        )
        return result.scalar() or 0
