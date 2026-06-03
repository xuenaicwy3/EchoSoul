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
        """同步包装，直接运行异步方法"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None and loop.is_running():
            # 当前在事件循环中，不能使用 run_until_complete，需要创建一个 future 并等待？
            # 实际上，在异步上下文中，这个同步方法本不应该被调用，但 LangGraph 可能会。
            # 我们采用 run_coroutine_threadsafe 方式调用，但这里简单返回 None，因为主要使用场景是在同步测试中。
            # 对于生产，我们确保主流程使用异步方法。
            # 更安全的方式：直接抛出异常，引导使用异步方法。
            raise RuntimeError("Cannot call synchronous get_tuple from within an async context. Use await acheckpoint.aget() instead.")
        else:
            # 不在事件循环中（例如测试或独立线程），可以安全运行
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