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
from app.config import Settings
from app.database import get_async_session
from app.roles import RoleCatalog
from app.prompts import PromptFactory
from app.affection import AffectionService
from app.redis_client import get_redis_client
from app.offline_service import OfflineService
from app.affective_memory_service import AffectiveMemoryService
from app.chat_history import ChatHistoryManager
from sqlalchemy import select, distinct
from app.models.db_models import ChatHistory as ChatHistoryModel

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
                await pipe.lrange(key, 0, -1)
                await pipe.delete(key)
                results = await pipe.execute()
                return results[0] if results else []
        except Exception as e:
            logger.error(f"获取待处理消息失败: {e}")
            return []

    async def _check_and_generate(self):
        """原有的主动消息扫描 + 新增的离线生活日志生成"""
        redis = get_redis_client()
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
                    prompt = PromptFactory.proactive_message(role, avg_aff)
                    loop = asyncio.get_running_loop()
                    resp = await loop.run_in_executor(None, self.llm.invoke, prompt)
                    msg = resp.content.strip()
                    await redis.rpush(pending_key, msg)
                    logger.info("已为用户 %s 生成主动消息", uid[:8])
            if cursor == 0:
                break

        # 好感度衰减（凌晨3点执行，加分布式锁防止多 worker 重复）
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

        # 新增：离线生活日志生成
        await self._generate_offline_life_logs(redis)

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