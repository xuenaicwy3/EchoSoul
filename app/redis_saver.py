"""
Redis 异步检查点存储器（同时支持同步调用）支持高并发
"""
import asyncio
import json
import logging
from typing import Optional
from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple
from app.redis_client import redis_client

logger = logging.getLogger(__name__)

CHECKPOINT_TTL = 3600  # 1小时过期

class RedisSaver(BaseCheckpointSaver):
    # ---- 异步接口（LangGraph 内部主要使用） ----
    async def aget(self, config: dict) -> Optional[CheckpointTuple]:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        key = f"checkpoint:{thread_id}:{checkpoint_ns}"
        data = await redis_client.get(key)
        if data:
            checkpoint = json.loads(data)
            return CheckpointTuple(config=config, checkpoint=checkpoint, metadata={})
        return None

    async def aput(self, config: dict, checkpoint: dict, metadata: dict) -> None:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        key = f"checkpoint:{thread_id}:{checkpoint_ns}"
        await redis_client.setex(key, CHECKPOINT_TTL, json.dumps(checkpoint))
        logger.debug(f"检查点已存储: {key}")

    # ---- 同步接口（LangGraph 在某些路径会调用，如 graph.get_state） ----
    def get_tuple(self, config: dict) -> Optional[CheckpointTuple]:
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                import concurrent.futures
                future = asyncio.run_coroutine_threadsafe(self.aget(config), loop)
                return future.result(timeout=5)
        except RuntimeError:
            pass
        return asyncio.run(self.aget(config))

    def put(self, config: dict, checkpoint: dict, metadata: dict) -> None:
        """同步包装"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None and loop.is_running():
            # 在异步上下文中，调度一个任务但不等待
            asyncio.run_coroutine_threadsafe(self.aput(config, checkpoint, metadata), loop)
        else:
            asyncio.run(self.aput(config, checkpoint, metadata))