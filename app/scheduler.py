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
            model=settings.LLM_MODEL, model_provider="openai",
            api_key=settings.DASHSCOPE_API_KEY,
            base_url=settings.DASHSCOPE_BASE_URL,
            temperature=0.75
        )
        self._scheduler = AsyncIOScheduler()

    async def update_active(self, user_id: str):
        redis = get_redis_client()
        await redis.setex(
            f"user:last_active:{user_id}",
            timedelta(hours=24),
            datetime.now().isoformat()
        )

    async def get_pending(self, user_id: str) -> List[str]:
        key = f"user:pending_messages:{user_id}"
        redis = get_redis_client()
        async with redis.pipeline() as pipe:
            await pipe.lrange(key, 0, -1)
            await pipe.delete(key)
            results = await pipe.execute()
        return results[0] if results else []

    async def _check_and_generate(self):
        redis = get_redis_client()
        keys = await redis.keys("user:last_active:*")
        for key in keys:
            uid = key.split(":")[-1]
            last_active_str = await redis.get(key)
            if not last_active_str:
                continue
            last_active = datetime.fromisoformat(last_active_str)
            if (datetime.now() - last_active) > timedelta(hours=self.settings.INACTIVE_HOURS):
                pending_key = f"user:pending_messages:{uid}"
                if await redis.exists(pending_key):
                    continue
                role_type = "温柔贤淑型"
                role = RoleCatalog.get_role(role_type)
                aff = await self.affection.get(uid, role_type)
                avg_aff = sum(aff.values()) / 4
                prompt = PromptFactory.proactive_message(role.name, role.persona, avg_aff)
                msg = self.llm.invoke(prompt).content.strip()
                await redis.rpush(pending_key, msg)
                logger.info("已为用户 %s 生成主动消息", uid[:8])
        now = datetime.now()
        if now.hour == 3 and now.minute < 5:
            await self.affection.apply_decay()

    def start(self):
        self._scheduler.add_job(
            self._check_and_generate,
            trigger=IntervalTrigger(minutes=self.settings.SCHEDULER_INTERVAL_MINUTES),
            id='proactive_check', replace_existing=True
        )
        self._scheduler.start()

    def shutdown(self):
        self._scheduler.shutdown()