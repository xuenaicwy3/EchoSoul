"""
消费后处理 Stream，执行数据库写入等异步操作 + WebSocket 推送
"""
import asyncio
import base64
import json
import logging

from app.game_service import GameService
from app.redis_client import get_redis_client
from app.agent import EchoSoulAgent
from app.config import Settings                # ← 新增导入
from app.websocket_manager import manager
from app.tts_service import TTSService


logger = logging.getLogger(__name__)

# 实例化游戏服务
settings = Settings()
game_service = GameService(settings)           # ← 新增实例化
tts_service = TTSService()

async def process_postprocess_stream(agent: EchoSoulAgent):
    r = get_redis_client()       # 同步调用，拿到异步客户端
    if r is None:
        logger.error("Redis 未初始化，后处理 Worker 退出")
        return

    group = "postprocess_workers"    # 消费者组名
    consumer = "post_worker_1"       # 当前消费者名称

    # 创建消费者组（如果不存在）
    try:
        await r.xgroup_create("postprocess_stream", group, mkstream=True)
    except Exception:
        pass

    while True:
        try:
            # 从 Stream 读取一条消息，阻塞 1 秒
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
                    # 调用 Agent 的 finalize_conversation 写入数据库
                    await agent.finalize_conversation(
                        user_id=task["user_id"],
                        role_type=task["role_type"],
                        user_message=task["user_input"],
                        ai_reply=task["ai_reply"],
                        emotion=task["emotion"],
                    )
                    # 确认消息已被处理（从 Stream 中移除）
                    await r.xack("postprocess_stream", group, msg_id)

                    # 推送 AI 回复到 WebSocket（如果启用）
                    # 如果有 WebSocket 连接，主动推送结果给客户端
                    if settings.USE_WEBSOCKET:
                        try:
                            # 1. 合成语音
                            audio_bytes = await tts_service.synthesize(task["ai_reply"],
                                                                       task.get("role_type", "日系动漫型"))
                            audio_b64 = base64.b64encode(audio_bytes).decode("utf-8") if audio_bytes else None

                            # 2. 推送文本 + 语音
                            await manager.send_personal_message(task["user_id"], {
                                "type": "chat_reply",
                                "task_id": task.get("task_id"),
                                "reply": task["ai_reply"],
                                "emotion": task["emotion"],
                                "audio": audio_b64  # 新增语音字段
                            })
                            logger.info(
                                f"WebSocket 推送成功: user={task['user_id'][:8]}, reply_length={len(task['ai_reply'])}")
                        except Exception as e:
                            # 语音合成失败不影响文本推送
                            logger.error(f"语音合成或推送失败: {e}")
                            try:
                                await manager.send_personal_message(task["user_id"], {
                                    "type": "chat_reply",
                                    "task_id": task.get("task_id"),
                                    "reply": task["ai_reply"],
                                    "emotion": task["emotion"],
                                    "audio": None
                                })
                            except Exception as push_err:
                                logger.error(f"文本推送也失败: {push_err}")

                    # 然后处理成就，即使失败也不影响消息消费
                    try:
                        await game_service.update_achievements(task["user_id"], task["role_type"], task["user_input"])
                    except Exception as e:
                        logger.error(f"成就更新失败: {e}")
        except Exception as e:
            logger.error(f"后处理 Worker 异常: {e}", exc_info=True)
            await asyncio.sleep(1)