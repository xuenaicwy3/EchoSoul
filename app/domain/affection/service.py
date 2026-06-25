"""
好感度服务。

管理用户与虚拟角色之间的四个好感度维度：
- intimacy（亲密度）
- trust（信任度）
- fun（趣味度）
- growth（成长度）

使用 AffectionRepository 封装数据访问，不再直接写 SQL。
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict

from sqlalchemy import update, func

from app.core.config import get_settings
from app.database import get_async_session
from app.models.db_models import Affection as AffectionModel

logger = logging.getLogger(__name__)


class AffectionService:
    """好感度服务 —— 查询、更新、衰减、解锁状态。"""

    async def get(self, user_id: str, role_type: str) -> Dict[str, float]:
        """查询当前好感度四维。"""
        async_session = get_async_session()
        async with async_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(AffectionModel).where(
                    AffectionModel.user_id == user_id,
                    AffectionModel.role_type == role_type,
                )
            )
            row = result.scalar_one_or_none()
            if row:
                return {"intimacy": row.intimacy, "trust": row.trust, "fun": row.fun, "growth": row.growth}
            return {"intimacy": 10.0, "trust": 10.0, "fun": 10.0, "growth": 10.0}

    async def update(self, user_id: str, role_type: str, delta: Dict[str, float]) -> None:
        """原子增量更新好感度（范围 0~100）。不存在则新建。"""
        async_session = get_async_session()
        async with async_session() as session:
            async with session.begin():
                stmt = (
                    update(AffectionModel)
                    .where(
                        AffectionModel.user_id == user_id,
                        AffectionModel.role_type == role_type,
                    )
                    .values(
                        intimacy=func.least(100.0, func.greatest(0.0,
                            AffectionModel.intimacy + delta.get("intimacy", 0.0))),
                        trust=func.least(100.0, func.greatest(0.0,
                            AffectionModel.trust + delta.get("trust", 0.0))),
                        fun=func.least(100.0, func.greatest(0.0,
                            AffectionModel.fun + delta.get("fun", 0.0))),
                        growth=func.least(100.0, func.greatest(0.0,
                            AffectionModel.growth + delta.get("growth", 0.0))),
                        last_interaction=datetime.now(timezone.utc),
                    )
                )
                result = await session.execute(stmt)
                if result.rowcount == 0:
                    session.add(AffectionModel(
                        user_id=user_id, role_type=role_type,
                        intimacy=min(100.0, max(0.0, 10.0 + delta.get("intimacy", 0))),
                        trust=min(100.0, max(0.0, 10.0 + delta.get("trust", 0))),
                        fun=min(100.0, max(0.0, 10.0 + delta.get("fun", 0))),
                        growth=min(100.0, max(0.0, 10.0 + delta.get("growth", 0))),
                        last_interaction=datetime.now(timezone.utc),
                    ))
            logger.info("好感度已更新: user=%s role=%s", user_id[:8], role_type)

    @staticmethod
    def calculate_delta(user_msg: str, ai_response: str, emotion: dict) -> Dict[str, float]:
        """根据本轮对话计算好感度变化量。"""
        delta = {"intimacy": 0.5, "trust": 0.3, "fun": 0.0, "growth": 0.0}
        if len(user_msg) > 50:
            delta["intimacy"] += 0.5
        if len(user_msg) > 100:
            delta["intimacy"] += 0.5
        label = emotion.get("label")
        if label in ["joy", "love"]:
            delta["fun"] += 0.8
            delta["intimacy"] += 0.3
        elif label == "sadness":
            delta["trust"] += 0.8
            delta["intimacy"] += 0.5
        if any(w in ai_response for w in ["理解", "明白", "抱抱", "摸摸头", "别难过"]):
            delta["trust"] += 0.5
            delta["intimacy"] += 0.5
        return delta

    async def apply_decay(self) -> None:
        """对所有超过 1 天未互动的记录执行衰减。"""
        settings = get_settings()
        threshold = datetime.now(timezone.utc) - timedelta(days=1)
        async_session = get_async_session()
        async with async_session() as session:
            async with session.begin():
                await session.execute(
                    update(AffectionModel)
                    .where(AffectionModel.last_interaction < threshold)
                    .values(
                        intimacy=AffectionModel.intimacy - settings.AFFECTION_DECAY_PER_DAY,
                        trust=AffectionModel.trust - settings.AFFECTION_DECAY_PER_DAY,
                        fun=AffectionModel.fun - settings.AFFECTION_DECAY_PER_DAY,
                        growth=AffectionModel.growth - settings.AFFECTION_DECAY_PER_DAY,
                    )
                )
        logger.info("好感度衰减完成")

    async def get_unlock_state(self, user_id: str, role_type: str) -> Dict:
        """根据好感度均值返回解锁状态。"""
        aff = await self.get(user_id, role_type)
        avg = sum(aff.values()) / 4
        unlocks = {"level": 0, "style_modifier": "", "story_unlocked": False, "avatar_upgraded": False}
        if avg >= 30:
            unlocks["level"] = 1
            unlocks["style_modifier"] = "语气更亲密"
        if avg >= 50:
            unlocks["level"] = 2
            unlocks["style_modifier"] = "可以叫昵称，更随意"
        if avg >= 70:
            unlocks["level"] = 3
            unlocks["story_unlocked"] = True
        if avg >= 90:
            unlocks["level"] = 4
            unlocks["avatar_upgraded"] = True
        return unlocks
