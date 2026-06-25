"""
Redis 客户端管理。

全局异步 Redis 客户端，在应用生命周期中初始化/关闭。
"""
import logging
from typing import Optional

import redis.asyncio as aioredis
from redis.asyncio import Redis

from app.core.config import Settings

logger = logging.getLogger(__name__)

_redis_client: Optional[Redis] = None


async def init_redis(settings: Settings) -> None:
    """初始化 Redis 连接。"""
    global _redis_client
    logger.info("正在连接 Redis: %s", settings.REDIS_URL)
    _redis_client = aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
        retry_on_timeout=True,
    )
    # 验证连接
    await _redis_client.ping()
    logger.info("Redis 连接成功")


async def close_redis() -> None:
    """关闭 Redis 连接。"""
    global _redis_client
    if _redis_client:
        await _redis_client.close()
        _redis_client = None
        logger.info("Redis 连接已关闭")


def get_redis_client() -> Redis:
    """获取 Redis 客户端。若未初始化则抛出异常。"""
    if _redis_client is None:
        raise RuntimeError("Redis 未初始化，请先调用 init_redis()")
    return _redis_client
