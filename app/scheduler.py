"""
主动消息调度器
使用 APScheduler 异步调度，定期检查非活跃用户并生成主动消息
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from langchain.chat_models import init_chat_model
from app.config import Settings
from app.roles import RoleCatalog
from app.prompts import PromptFactory
from app.affection import AffectionService
from app.redis_client import get_redis_client

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
        key = f"user:pending_messages:{user_id}"
        redis = get_redis_client()
        async with redis.pipeline() as pipe:
            await pipe.lrange(key, 0, -1)
            await pipe.delete(key)
            results = await pipe.execute()
        return results[0] if results else []

    async def _check_and_generate(self):
        """扫描非活跃用户，生成主动消息"""
        redis = get_redis_client()
        # 使用 scan_iter 替代 keys（生产环境推荐）
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
                    role_type = "温柔贤淑型"
                    role = RoleCatalog.get_role(role_type)
                    aff = await self.affection.get(uid, role_type)
                    avg_aff = sum(aff.values()) / 4
                    prompt = PromptFactory.proactive_message(
                        role.name, role.persona, avg_aff
                    )
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