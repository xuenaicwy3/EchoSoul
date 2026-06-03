import json
import logging
import uuid
import redis.asyncio as aioredis
from redis.asyncio import Redis
from app.config import Settings
from typing import Optional

redis_client: Optional[Redis] = None

async def init_redis(settings: Settings):
    global redis_client
    logging.info(f"[InitRedis] 开始连接 Redis: {settings.REDIS_URL}")
    redis_client = aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=5,  # 连接超时
        socket_timeout=5,  # 读超时
        retry_on_timeout=True,  # 超时重试
    )
    logging.info("[InitRedis] Redis 连接成功，redis_client 已设置")


async def close_redis():
    global redis_client
    if redis_client:
        await redis_client.close()

# 发布聊天任务到Stream
async def publish_chat_task(user_id: str, task_info: dict) -> str:
    """将聊天任务信息发布到 Stream，返回 task_id"""
    task_id = str(uuid.uuid4())
    task_info["task_id"] = task_id
    # 将整个任务对象序列化后存入 Stream
    await redis_client.xadd("chat_stream", {"data": json.dumps(task_info)})
    return task_id


# 获取任务结果（轮询用）
async def get_task_result(task_id: str) -> dict | None:
    import json
    result = await redis_client.get(f"chat_result:{task_id}")
    if result:
        return json.loads(result)
    return None

def get_redis_client() -> Redis:
    if redis_client is None:
        raise RuntimeError("Redis 未初始化，请先调用 init_redis")
    return redis_client

async def get_chat_result(task_id: str) -> dict | None:
    """获取 Worker 处理后的结果"""
    result = await redis_client.get(f"chat_result:{task_id}")
    if result:
        return json.loads(result)
    return None


# 新增后处理任务发布函数
async def publish_postprocess(task_info: dict):
    await redis_client.xadd(
        "postprocess_stream",
        {"data": json.dumps(task_info)}
    )