"""
消费后处理 Stream，执行数据库写入等异步操作
"""
import asyncio
import json
import logging
from app.redis_client import get_redis_client
from app.agent import EchoSoulAgent

logger = logging.getLogger(__name__)

async def process_postprocess_stream(agent: EchoSoulAgent):
    r = get_redis_client()
    if r is None:
        logger.error("Redis 未初始化，后处理 Worker 退出")
        return

    group = "postprocess_workers"
    consumer = "post_worker_1"

    # 创建消费者组
    try:
        await r.xgroup_create("postprocess_stream", group, mkstream=True)
    except Exception:
        pass

    while True:
        try:
            messages = await r.xreadgroup(
                groupname=group,
                consumername=consumer,
                streams={"postprocess_stream": ">"},
                count=1,
                block=1000
            )
            if not messages:
                continue

            for stream, msg_list in messages:
                for msg_id, msg_data in msg_list:
                    data_str = msg_data.get("data")
                    if not data_str:
                        await r.xack("postprocess_stream", group, msg_id)
                        continue

                    task = json.loads(data_str)
                    await agent.finalize_conversation(
                        user_id=task["user_id"],
                        role_type=task["role_type"],
                        user_message=task["user_input"],
                        ai_reply=task["ai_reply"],
                        emotion=task["emotion"],
                    )
                    await r.xack("postprocess_stream", group, msg_id)
        except Exception as e:
            logger.error(f"后处理 Worker 异常: {e}", exc_info=True)
            await asyncio.sleep(1)