import logging
from typing import Dict
from datetime import datetime, timedelta
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.database import get_async_session
from app.models.db_models import Affection as AffectionModel

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

    async def update(self, user_id: str, role_type: str, delta: Dict[str, float]):
        current = await self.get(user_id, role_type)
        new_vals = {}
        for dim in ["intimacy", "trust", "fun", "growth"]:
            new_vals[dim] = max(0.0, min(100.0, current[dim] + delta.get(dim, 0.0)))

        async_session = get_async_session()
        async with async_session() as session:
            async with session.begin():
                stmt = pg_insert(AffectionModel).values(
                    user_id=user_id, role_type=role_type,
                    intimacy=new_vals["intimacy"], trust=new_vals["trust"],
                    fun=new_vals["fun"], growth=new_vals["growth"],
                    last_interaction=datetime.utcnow()
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=[AffectionModel.user_id, AffectionModel.role_type],
                    set_={
                        "intimacy": stmt.excluded.intimacy,
                        "trust": stmt.excluded.trust,
                        "fun": stmt.excluded.fun,
                        "growth": stmt.excluded.growth,
                        "last_interaction": stmt.excluded.last_interaction
                    }
                )
                await session.execute(stmt)
            logger.info("好感度更新: %s -> %s", role_type, new_vals)

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