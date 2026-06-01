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
        """
        这里 Redis 就是用来记录你最后一次发消息的时间。
        Key 是 user:last_active:你的用户ID，Value 是 2026-06-01T21:30:00。
        """
        redis = get_redis_client()
        await redis.setex(
            f"user:last_active:{user_id}",  # Redis 的 Key，例如 user:last_active:web_user_xxxx
            timedelta(hours=24),                  # 过期时间
            datetime.now().isoformat()            # 当前时间，如 "2026-06-01T21:30:00"
        )

    async def get_pending(self, user_id: str) -> List[str]:
        """后端去 Redis 的对应列表里，把所有消息取出来，发给前端，然后删掉 Redis 中的数据（避免重复推送）"""
        key = f"user:pending_messages:{user_id}"
        # 一次性取出所有消息，并删除 Redis 中的 Key
        redis = get_redis_client()
        async with redis.pipeline() as pipe:
            await pipe.lrange(key, 0, -1)    # 取出所有消息
            await pipe.delete(key)                # 清空列表
            results = await pipe.execute()
        return results[0] if results else []


    # 1. 扫描所有用户的最后活跃时间
    async def _check_and_generate(self):
        """
        就像 QQ 会给你推送“你的好友上线了”一样，这里 AI 会在你长时间不说话时，生成一句主动问候语，放到一个“待推送消息列表”里。
        Key 是 user:pending_messages:你的用户ID，Value 是一个消息列表。
        """
        redis = get_redis_client()
        keys = await redis.keys("user:last_active:*")
        for key in keys:
            uid = key.split(":")[-1]            # 提取用户 ID
            last_active_str = await redis.get(key)   # 取出最后活跃时间
            if not last_active_str:
                continue
            last_active = datetime.fromisoformat(last_active_str)

            # 2. 如果超过 2 小时没说话，生成主动消息
            if (datetime.now() - last_active) > timedelta(hours=self.settings.INACTIVE_HOURS):
                pending_key = f"user:pending_messages:{uid}"
                if await redis.exists(pending_key):
                    continue
                role_type = "温柔贤淑型"
                role = RoleCatalog.get_role(role_type)
                aff = await self.affection.get(uid, role_type)
                avg_aff = sum(aff.values()) / 4
                prompt = PromptFactory.proactive_message(role.name, role.persona, avg_aff)

                # 3. 生成消息（调用 LLM）
                msg = self.llm.invoke(prompt).content.strip()

                # 4. 把消息存入 Redis 的 List 中（队列）
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