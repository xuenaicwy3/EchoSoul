"""
这个文件是一个好感度服务，管理用户和虚拟角色之间的四个好感维度：
intimacy（亲密度）：关系有多亲近
trust（信任度）：角色有多信任用户
fun（趣味度）：对话是否有趣
growth（成长度）：角色的成长进度
每个维度的范围都是 0 ~ 100，初始值为 10。
"""
import logging
from typing import Dict
from datetime import datetime, timedelta
from sqlalchemy import select, update
from app.config import Settings
from app.database import get_async_session
from app.models.db_models import Affection as AffectionModel
from sqlalchemy import update, func   # 顶部添加导入
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class AffectionService:
    # 查询当前好感度
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


    # 原子更新好感度（核心）
    async def update(self, user_id: str, role_type: str, delta: Dict[str, float]):
        async_session = get_async_session()
        async with async_session() as session:
            async with session.begin():           # 开启事务
                # 原子增量更新，同时限制范围 0~100
                # 构造更新语句
                # “原子更新” 就是把“读-改-写”放在一个数据库命令里，由数据库在行锁保护下完成。
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
                # 如果没有记录被更新（rowcount==0），说明表里没有该行，需要插入
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
        # 创建一个字典，包含四个键：intimacy（亲密度）、trust（信任度）、fun（趣味度）、growth（成长度）。
        # 初始值：每次聊天至少会让亲密度 +0.5，信任度 +0.3，趣味度和成长度初始为 0（需要特殊条件才增加）。
        delta = {"intimacy": 0.5, "trust": 0.3, "fun": 0.0, "growth": 0.0}
        if len(user_msg) > 50:
            delta["intimacy"] += 0.5   # 亲密度额外 +0.5
        if len(user_msg) > 100:
            delta["intimacy"] += 0.5
        label = emotion.get("label")
        if label in ["joy", "love"]:  # 当用户情绪是 快乐（joy）或爱意（love）
            delta["fun"] += 0.8   # 趣味度 +0.8
            delta["intimacy"] += 0.3  # 亲密度 +0.3
        elif label == "sadness":   # 当用户情绪是 悲伤
            delta["trust"] += 0.8  # 信任度 +0.8
            delta["intimacy"] += 0.5
        if any(w in ai_response for w in ["理解", "明白", "抱抱", "摸摸头", "别难过"]):
            delta["trust"] += 0.5   # 信任度 +0.5
            delta["intimacy"] += 0.5  # 亲密度 +0.5
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
                        intimacy=AffectionModel.intimacy - Settings.AFFECTION_DECAY_PER_DAY,
                        trust=AffectionModel.trust - Settings.AFFECTION_DECAY_PER_DAY,
                        fun=AffectionModel.fun - Settings.AFFECTION_DECAY_PER_DAY,
                        growth=AffectionModel.growth - Settings.AFFECTION_DECAY_PER_DAY
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