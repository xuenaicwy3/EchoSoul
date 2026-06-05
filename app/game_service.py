import logging
from datetime import date, datetime, timedelta
from sqlalchemy import select, update, func
from app.database import get_async_session
from app.models.db_models import (
    DailyTaskTemplate, UserDailyTask, Achievement, UserAchievement,
    Skin, UserSkin, Affection as AffectionModel
)
from app.config import Settings
from datetime import datetime, timezone
from app.websocket_manager import manager

logger = logging.getLogger(__name__)

class GameService:
    def __init__(self, settings: Settings):
        self.settings = settings

    # app/game_service.py（在 GameService 类中添加）
    async def init_game_data(self):
        """初始化游戏基础数据（幂等操作，多次启动安全）"""
        session = get_async_session()
        async with session() as s:
            # ---------- 每日任务模板 ----------
            result = await s.execute(select(func.count()).select_from(DailyTaskTemplate))
            if result.scalar() == 0:
                tasks = [
                    DailyTaskTemplate(name='早安问候', description='向伴侣说一句早安', reward_intimacy=5.0),
                    DailyTaskTemplate(name='分享一天', description='告诉伴侣今天发生的有趣事情', reward_intimacy=5.0),
                    DailyTaskTemplate(name='晚安道别', description='睡前和伴侣道一声晚安', reward_intimacy=5.0),
                ]
                s.add_all(tasks)
                logger.info("每日任务模板初始化完成")

            # ---------- 成就 ----------
            result = await s.execute(select(func.count()).select_from(Achievement))
            if result.scalar() == 0:
                achievements = [
                    Achievement(name='初来乍到', description='累计聊天100字', category='chat_length', threshold=100,
                                reward_intimacy=10.0),
                    Achievement(name='话唠', description='累计聊天1000字', category='chat_length', threshold=1000,
                                reward_intimacy=20.0),
                    Achievement(name='文豪', description='累计聊天10000字', category='chat_length', threshold=10000,
                                reward_intimacy=30.0),
                ]
                s.add_all(achievements)
                logger.info("成就数据初始化完成")

            # ---------- 皮肤 ----------
            result = await s.execute(select(func.count()).select_from(Skin))
            if result.scalar() == 0:
                skins = [
                    Skin(role_type='日系动漫型', name='原版', description='默认外观', unlock_condition='无',
                         unlock_type='', unlock_value=0),
                    Skin(role_type='日系动漫型', name='夏日祭', description='夏日祭限定外观',
                         unlock_condition='亲密度达到30', unlock_type='intimacy', unlock_value=30),
                    Skin(role_type='温柔贤淑型', name='原版', description='默认外观', unlock_condition='无',
                         unlock_type='', unlock_value=0),
                    Skin(role_type='高冷御姐型', name='原版', description='默认外观', unlock_condition='无',
                         unlock_type='', unlock_value=0),
                    # 可继续添加其他角色的皮肤...
                ]
                s.add_all(skins)
                logger.info("皮肤数据初始化完成")

            await s.commit()

    # ---------- 养成系统 ----------
    async def get_unlock_info(self, user_id: str, role_type: str) -> dict:
        """根据亲密度返回解锁状态"""
        aff = await self._get_affection(user_id, role_type)
        intimacy = aff.get("intimacy", 10.0)

        logger.info(f"获取好感度: user={user_id}, role={role_type}, aff={aff}")

        return {
            "intimacy": intimacy,  # ← 必须包含这个字段
            "memory_expansion": intimacy >= 50,          # 记忆容量扩容
            "special_actions": intimacy >= 30,           # 专属互动动作
            "new_topics": intimacy >= 20,                # 新对话话题
        }

    # ---------- 每日任务 ----------
    async def get_daily_tasks(self, user_id: str, role_type: str) -> list:
        """获取用户今日任务，若未分配则自动分配"""
        today = date.today()
        session = get_async_session()
        async with session() as s:
            # 查询今日任务
            stmt = select(UserDailyTask).where(
                UserDailyTask.user_id == user_id,
                UserDailyTask.role_type == role_type,
                UserDailyTask.date == today
            )
            result = await s.execute(stmt)
            tasks = result.scalars().all()

            if not tasks:
                # 自动分配：随机选取3个任务模板
                stmt = select(DailyTaskTemplate).order_by(func.random()).limit(3)
                result = await s.execute(stmt)
                templates = result.scalars().all()

                for tpl in templates:
                    new_task = UserDailyTask(
                        user_id=user_id,
                        role_type=role_type,
                        task_template_id=tpl.id,
                        date=today
                    )
                    s.add(new_task)
                await s.commit()

                # 重新查询
                result = await s.execute(select(UserDailyTask).where(
                    UserDailyTask.user_id == user_id,
                    UserDailyTask.role_type == role_type,
                    UserDailyTask.date == today
                ))
                tasks = result.scalars().all()

            # 组装返回
            task_list = []
            for t in tasks:
                tpl = await s.get(DailyTaskTemplate, t.task_template_id)
                task_list.append({
                    "id": t.id,
                    "name": tpl.name,
                    "description": tpl.description,
                    "reward_intimacy": tpl.reward_intimacy,
                    "completed": t.completed
                })
            return task_list

    async def complete_daily_task(self, user_id: str, role_type: str, task_id: int):
        """完成某个每日任务，发放奖励"""
        session = get_async_session()
        async with session() as s:
            task = await s.get(UserDailyTask, task_id)
            if not task or task.user_id != user_id or task.completed:
                return {"success": False, "message": "任务无效或已完成"}

            # 标记完成
            task.completed = True
            task.completion_time = datetime.utcnow()

            # 发放亲密度奖励
            tpl = await s.get(DailyTaskTemplate, task.task_template_id)
            reward = tpl.reward_intimacy
            # 更新好感度（原子操作）
            stmt = update(AffectionModel).where(
                AffectionModel.user_id == user_id,
                AffectionModel.role_type == role_type
            ).values(
                intimacy=func.least(100.0, AffectionModel.intimacy + reward)
            )
            await s.execute(stmt)
            await s.commit()
            return {"success": True, "reward_intimacy": reward}

    # ---------- 成就系统 ----------
    async def get_achievements(self, user_id: str) -> list:
        """获取用户所有成就及进度"""
        session = get_async_session()
        async with session() as s:
            # 查询所有成就
            result = await s.execute(select(Achievement))
            all_achievements = result.scalars().all()

            # 查询用户进度
            result = await s.execute(select(UserAchievement).where(
                UserAchievement.user_id == user_id
            ))
            user_ach_list = {a.achievement_id: a for a in result.scalars().all()}

            ret = []
            for ach in all_achievements:
                user_ach = user_ach_list.get(ach.id)
                ret.append({
                    "id": ach.id,
                    "name": ach.name,
                    "description": ach.description,
                    "threshold": ach.threshold,
                    "progress": user_ach.progress if user_ach else 0,
                    "completed": user_ach.completed if user_ach else False,
                    "reward_intimacy": ach.reward_intimacy
                })
            return ret


    async def update_achievements(self, user_id: str, role_type: str, message: str):
        """在每次对话后调用，更新成就进度（聊天字数、连续天数等）"""
        session = get_async_session()
        async with session() as s:
            # 更新聊天字数成就
            word_count = len(message)
            ach = await s.execute(select(Achievement).where(
                Achievement.category == "chat_length"
            ))
            for a in ach.scalars().all():
                # 查询用户成就进度（用 select 代替 get，因为主键是自增 id）
                result = await s.execute(
                    select(UserAchievement).where(
                        UserAchievement.user_id == user_id,
                        UserAchievement.achievement_id == a.id
                    )
                )
                user_ach = result.scalar_one_or_none()

                if not user_ach:
                    user_ach = UserAchievement(
                        user_id=user_id,
                        achievement_id=a.id,
                        progress=0
                    )
                    s.add(user_ach)

                if not user_ach.completed:
                    user_ach.progress += word_count
                    if user_ach.progress >= a.threshold:
                        user_ach.progress = a.threshold
                        user_ach.completed = True
                        user_ach.completed_at = datetime.now(timezone.utc)  # 使用带时区的时间
                        # 发放奖励
                        await self._grant_intimacy(user_id, role_type, a.reward_intimacy)

                        # WebSocket 推送成就解锁
                        if self.settings.USE_WEBSOCKET:
                            await manager.send_personal_message(user_id, {
                                "type": "achievement",
                                "content": f"🏆 成就解锁：{a.name}"
                            })


            await s.commit()


    async def _grant_intimacy(self, user_id: str, role_type: str, amount: float):
        """发放亲密度"""
        session = get_async_session()
        async with session() as s:
            stmt = update(AffectionModel).where(
                AffectionModel.user_id == user_id,
                AffectionModel.role_type == role_type
            ).values(
                intimacy=func.least(100.0, AffectionModel.intimacy + amount)
            )
            await s.execute(stmt)
            await s.commit()

    async def _get_affection(self, user_id: str, role_type: str) -> dict:
        session = get_async_session()
        async with session() as s:
            result = await s.execute(select(AffectionModel).where(
                AffectionModel.user_id == user_id,
                AffectionModel.role_type == role_type
            ))
            row = result.scalar_one_or_none()
            if row:
                return {"intimacy": row.intimacy, "trust": row.trust, "fun": row.fun, "growth": row.growth}
            return {"intimacy": 10.0, "trust": 10.0, "fun": 10.0, "growth": 10.0}

    # ---------- 皮肤系统 ----------
    async def get_skins(self, user_id: str, role_type: str) -> list:
        """获取指定角色的皮肤列表及解锁状态"""
        session = get_async_session()
        async with session() as s:
            result = await s.execute(select(Skin).where(Skin.role_type == role_type))
            skins = result.scalars().all()

            # 查询用户拥有的皮肤
            result = await s.execute(select(UserSkin).where(
                UserSkin.user_id == user_id,
                UserSkin.role_type == role_type
            ))
            user_skins = {us.skin_id: us for us in result.scalars().all()}

            ret = []
            for skin in skins:
                us = user_skins.get(skin.id)
                ret.append({
                    "id": skin.id,
                    "name": skin.name,
                    "description": skin.description,
                    "unlock_condition": skin.unlock_condition,
                    "unlocked": us is not None,
                    "equipped": us.equipped if us else False
                })
            return ret

    async def equip_skin(self, user_id: str, role_type: str, skin_id: int):
        """装备指定皮肤"""
        session = get_async_session()
        async with session() as s:
            # 取消当前角色的所有装备状态
            stmt = update(UserSkin).where(
                UserSkin.user_id == user_id,
                UserSkin.role_type == role_type
            ).values(equipped=False)
            await s.execute(stmt)

            # 装备新皮肤
            stmt = update(UserSkin).where(
                UserSkin.user_id == user_id,
                UserSkin.role_type == role_type,
                UserSkin.skin_id == skin_id
            ).values(equipped=True)
            await s.execute(stmt)
            await s.commit()
            return {"success": True}