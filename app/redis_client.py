import logging

import redis.asyncio as aioredis
from redis.asyncio import Redis
from app.config import Settings
from typing import Optional

redis_client: Optional[Redis] = None

async def init_redis(settings: Settings):
    global redis_client
    logging.info(f"[InitRedis] 开始连接 Redis: {settings.REDIS_URL}")
    redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    logging.info("[InitRedis] Redis 连接成功，redis_client 已设置")

async def close_redis():
    global redis_client
    if redis_client:
        await redis_client.close()
        redis_client = None


def get_redis_client() -> Redis:
    if redis_client is None:
        raise RuntimeError("Redis 未初始化，请先调用 init_redis")
    return redis_client