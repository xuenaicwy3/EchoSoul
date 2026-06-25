"""
主动消息调度器
使用 APScheduler 异步调度，定期检查非活跃用户并生成主动消息
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from langchain.chat_models import init_chat_model
from sqlalchemy.sql.expression import delete

from app.core.config import get_settings, Settings
from app.infrastructure.database import get_async_session
from app.domain.roles.catalog import RoleCatalog
from app.domain.agent.prompts import PromptFactory
from app.domain.affection.service import AffectionService
from app.infrastructure.redis import get_redis_client
from app.offline_service import OfflineService
from app.affective_memory_service import AffectiveMemoryService
from app.chat_history import ChatHistoryManager
from sqlalchemy import select, distinct
from app.models.db_models import ChatHistory as ChatHistoryModel, UserFact, EmotionRecord, RelationshipMilestone

logger = logging.getLogger(__name__)


class ProactiveScheduler:
    def __init__(self, settings: Settings, affection_service: AffectionService):
        self.settings = settings
        self.affection = affection_service
        self.llm = init_chat_model(
            model=settings.LLM_MODEL,
            model_provider="openai",
            api_key=settings.DASHSCOPE_API_KEY,
            base_url=settings.DASHSCOPE_BASE_URL,
            temperature=0.75,
        )
        self._scheduler = AsyncIOScheduler()

    async def update_active(self, user_id: str):
        """记录用户最后活跃时间（Redis）"""
        redis = get_redis_client()
        await redis.sadd("active_users", user_id)
        await redis.setex(
            f"user:last_active:{user_id}",
            timedelta(hours=24),
            datetime.now().isoformat(),
        )


    async def get_pending(self, user_id: str) -> List[str]:
        """获取待推送的主动消息并清空队列"""
        try:
            key = f"user:pending_messages:{user_id}"
            redis = get_redis_client()
            async with redis.pipeline() as pipe:
                await pipe.lrange(key, 0, -1)   # 获取队列所有消息
                await pipe.delete(key)               # 获取后清空队列
                results = await pipe.execute()
                return results[0] if results else []
        except Exception as e:
            logger.error(f"获取待处理消息失败: {e}")
            return []

    async def _check_and_generate(self):
        """定时任务主入口：主动消息 + 好感度衰减 + 离线日志 + 记忆整理"""
        redis = get_redis_client()
        # ---- 1、生成主动消息 ----
        # 扫描不活跃用户并生成主动消息
        cursor = 0
        while True:
            cursor, keys = await redis.scan(
                cursor, match="user:last_active:*", count=100
            )
            for key in keys:
                uid = key.split(":")[-1]
                last_active_str = await redis.get(key)
                if not last_active_str:
                    continue
                last_active = datetime.fromisoformat(last_active_str)
                # 如果用户超过 INACTIVE_HOURS 小时未活跃
                if (datetime.now() - last_active) > timedelta(
                    hours=self.settings.INACTIVE_HOURS
                ):
                    pending_key = f"user:pending_messages:{uid}"
                    if await redis.exists(pending_key):
                        continue
                    role_type = "日系动漫美少女型"
                    role = RoleCatalog.get_role(role_type)
                    aff = await self.affection.get(uid, role_type)
                    avg_aff = sum(aff.values()) / 4
                    # 调用 LLM 生成主动消息
                    prompt = PromptFactory.proactive_message(role, avg_aff)
                    loop = asyncio.get_running_loop()
                    resp = await loop.run_in_executor(None, self.llm.invoke, prompt)
                    msg = resp.content.strip()
                    await redis.rpush(pending_key, msg)
                    logger.info("已为用户 %s 生成主动消息", uid[:8])
            if cursor == 0:
                break

        # --- 2. 好感度衰减（凌晨3点） ---
        now = datetime.now()
        if now.hour == 3 and now.minute < 5:
            lock_key = "affection_decay_lock"
            acquired = await redis.set(lock_key, "1", nx=True, ex=300)
            if acquired:
                try:
                    await self.affection.apply_decay()
                    logger.info("好感度衰减已执行")
                finally:
                    await redis.delete(lock_key)

        # --- 3. 离线生活日志生成 ---
        await self._generate_offline_life_logs(redis)

        # --- 4. 三层记忆睡眠整理（凌晨3点） ---
        await self._run_memory_consolidation(redis, now)


    async def _generate_offline_life_logs(self, redis):
        """为长时间未活动的用户生成生活日志，并推送到离线队列"""
        offline_svc = OfflineService(self.settings)
        chat_history_mgr = ChatHistoryManager()
        affective_memory_svc = AffectiveMemoryService(self.settings)

        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor, match="user:last_active:*", count=100)
            for key in keys:
                uid = key.split(":")[-1]
                last_active_str = await redis.get(key)
                if not last_active_str:
                    continue
                last_active = datetime.fromisoformat(last_active_str)
                if (datetime.now() - last_active) > timedelta(hours=self.settings.INACTIVE_HOURS):
                    session = get_async_session()
                    async with session() as s:
                        roles_result = await s.execute(
                            select(distinct(ChatHistoryModel.role_type)).where(
                                ChatHistoryModel.user_id == uid
                            )
                        )
                        roles = [row[0] for row in roles_result.fetchall()]

                    for role_type in roles:
                        user_settings = await offline_svc.get_settings(uid, role_type)
                        if not user_settings.get("life_log_enabled", True):
                            continue

                        last_logs = await offline_svc.get_life_logs(uid, role_type, limit=1)
                        if last_logs:
                            last_log_time = datetime.fromisoformat(last_logs[0]["time"])
                            if (datetime.now(timezone.utc) - last_log_time) < timedelta(hours=6):
                                continue

                        history = await chat_history_mgr.get_history(uid, role_type, limit=5)
                        chat_text = "\n".join(
                            [f"{'用户' if h['sender'] == 'user' else 'AI'}：{h['message']}" for h in history])

                        facts = await affective_memory_svc.get_facts(uid, role_type)
                        facts_text = "\n".join([f"{f['key']}: {f['value']}" for f in facts]) if facts else ""

                        content = await offline_svc.generate_life_log(uid, role_type, chat_text, facts_text)
                        if content:
                            # 1. 保存到数据库（新增）
                            await chat_history_mgr.add_message(
                                user_id=uid,
                                role_type=role_type,
                                sender="ai",  # 作为 AI 消息存储
                                message=f"💌 你的伙伴写下了新的生活日志：{content}"  # 完整日志内容
                            )

                            # 2. 推送到 Redis 离线队列
                            await offline_svc.save_life_log(uid, role_type, content)
                            await offline_svc.push_message_to_user(
                                uid, role_type,
                                f"💌 你的伙伴写下了新的生活日志：{content[:100]}...",
                                use_ws=False
                            )

                            # 3. 保存到专门的 life_logs 表（如果还希望单独管理日志）
                            await offline_svc.save_life_log(uid, role_type, content)

                            logger.info(f"离线日志已生成并推送: user={uid[:8]}, role={role_type}")

            if cursor == 0:
                break


    async def _run_memory_consolidation(self, redis, now: datetime):
        """
        在凌晨3点执行记忆整理（分布式锁保护）。

        这是一个定时后台任务，负责在系统低峰期（凌晨3点）对全局所有用户的
        记忆进行统一整理和压缩，包括事实归档、情绪聚合、里程碑压缩等操作。
        使用 Redis 分布式锁确保在多实例部署下只有一个实例执行该任务，
        避免重复处理和资源冲突。

        :param redis: Redis 客户端实例（用于分布式锁）
        :param now: 当前时间（用于判断是否到达执行窗口）
        """
        if now.hour != 3 or now.minute >= 5:
            return
        lock_key = "memory_consolidation_lock"
        acquired = await redis.set(lock_key, "1", nx=True, ex=300)
        if not acquired:
            return
        try:
            logger.info("开始全局记忆睡眠整理...")
            svc = AffectiveMemoryService(self.settings)

            # ---------- 4. 获取所有需要整理的用户-角色对 ----------
            # 从三个记忆表中分别查询去重的 (user_id, role_type) 组合，并用 UNION 合并
            # 确保任何有事实、情绪或里程碑记录的用户都会被纳入整理范围
            session = get_async_session()
            async with session() as s:
                # 合并查询事实表和情绪表中的用户-角色对
                query = select(distinct(UserFact.user_id), UserFact.role_type).union(
                    select(distinct(EmotionRecord.user_id), EmotionRecord.role_type)
                ).union(
                    select(distinct(RelationshipMilestone.user_id), RelationshipMilestone.role_type)
                )
                result = await s.execute(query)
                pairs = result.all()

                # ---------- 5. 对每个用户-角色对执行记忆整理 ----------
                for user_id, role_type in pairs:
                    await svc.memory_consolidation(user_id, role_type)
            logger.info("全局记忆睡眠整理完成")
        except Exception as e:
            logger.error(f"记忆整理失败: {e}", exc_info=True)
        finally:
            await redis.delete(lock_key)


    def start(self):
        self._scheduler.add_job(
            self._check_and_generate,
            trigger=IntervalTrigger(minutes=self.settings.SCHEDULER_INTERVAL_MINUTES),
            id="proactive_check",
            replace_existing=True,
        )
        self._scheduler.start()

    def shutdown(self):
        self._scheduler.shutdown()


