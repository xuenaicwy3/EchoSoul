"""
消费后处理 Stream，执行数据库写入等异步操作
"""
import asyncio
import json
import logging

from app.game_service import GameService
from app.redis_client import get_redis_client
from app.agent import EchoSoulAgent
from app.config import Settings                # ← 新增导入
from app.websocket_manager import manager

logger = logging.getLogger(__name__)

# 实例化游戏服务
settings = Settings()
game_service = GameService(settings)           # ← 新增实例化

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

                    # 推送 AI 回复到 WebSocket（如果启用）
                    if settings.USE_WEBSOCKET:
                        try:
                            await manager.send_personal_message(task["user_id"], {
                                "type": "chat_reply",
                                "task_id": task.get("task_id"),
                                "reply": task["ai_reply"],
                                "emotion": task["emotion"]
                            })
                            logger.info(
                                f"WebSocket 推送成功: user={task['user_id'][:8]}, reply_length={len(task['ai_reply'])}")
                        except Exception as e:
                            logger.error(f"WebSocket 推送失败: {e}")

                    # 然后处理成就，即使失败也不影响消息消费
                    try:
                        await game_service.update_achievements(task["user_id"], task["role_type"], task["user_input"])
                    except Exception as e:
                        logger.error(f"成就更新失败: {e}")
        except Exception as e:
            logger.error(f"后处理 Worker 异常: {e}", exc_info=True)
            await asyncio.sleep(1)