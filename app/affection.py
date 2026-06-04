import logging
from typing import Dict
from datetime import datetime, timedelta
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.database import get_async_session
from app.models.db_models import Affection as AffectionModel
from sqlalchemy import update, func   # 顶部添加导入
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class AffectionService:
    async def get(self, user_id: str, role_type: str) -> Dict[str, float]:
        async_session = get_async_session()
        async with async_session() as session:
            result = await session.execute(
                select(AffectionModel).where(
                    AffectionModel.user_id == user_id,
                    AffectionModel.role_type == role_type
                )
            )
            row = result.scalar_one_or_none()
            if row:
                return {"intimacy": row.intimacy, "trust": row.trust, "fun": row.fun, "growth": row.growth}
            return {"intimacy": 10.0, "trust": 10.0, "fun": 10.0, "growth": 10.0}

    from sqlalchemy import update, func  # 顶部添加导入

    async def update(self, user_id: str, role_type: str, delta: Dict[str, float]):
        async_session = get_async_session()
        async with async_session() as session:
            async with session.begin():
                # 原子增量更新，同时限制范围 0~100
                stmt = (
                    update(AffectionModel)
                    .where(
                        AffectionModel.user_id == user_id,
                        AffectionModel.role_type == role_type
                    )
                    .values(
                        intimacy=func.least(100.0,
                                            func.greatest(0.0, AffectionModel.intimacy + delta.get("intimacy", 0.0))),
                        trust=func.least(100.0, func.greatest(0.0, AffectionModel.trust + delta.get("trust", 0.0))),
                        fun=func.least(100.0, func.greatest(0.0, AffectionModel.fun + delta.get("fun", 0.0))),
                        growth=func.least(100.0, func.greatest(0.0, AffectionModel.growth + delta.get("growth", 0.0))),
                        last_interaction=datetime.now(timezone.utc)
                    )
                )
                result = await session.execute(stmt)

                # 如果没有命中行，说明记录还不存在，插入初始值
                if result.rowcount == 0:
                    session.add(AffectionModel(
                        user_id=user_id,
                        role_type=role_type,
                        intimacy=min(100.0, max(0.0, 10.0 + delta.get("intimacy", 0))),
                        trust=min(100.0, max(0.0, 10.0 + delta.get("trust", 0))),
                        fun=min(100.0, max(0.0, 10.0 + delta.get("fun", 0))),
                        growth=min(100.0, max(0.0, 10.0 + delta.get("growth", 0))),
                        last_interaction=datetime.utcnow()
                    ))

            logger.info("好感度已更新: user=%s, role=%s", user_id[:8], role_type)

    def calculate_delta(self, user_msg: str, ai_response: str, emotion: dict) -> Dict[str, float]:
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

    async def apply_decay(self):
        threshold = datetime.utcnow() - timedelta(days=1)
        async_session = get_async_session()
        async with async_session() as session:
            async with session.begin():
                await session.execute(
                    update(AffectionModel)
                    .where(AffectionModel.last_interaction < threshold)
                    .values(
                        intimacy=AffectionModel.intimacy - 2.0,
                        trust=AffectionModel.trust - 2.0,
                        fun=AffectionModel.fun - 2.0,
                        growth=AffectionModel.growth - 2.0
                    )
                )
        logger.info("好感度衰减完成")

    async def get_unlock_state(self, user_id: str, role_type: str) -> Dict:
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