"""
后处理 Worker。

两部分：
1. Redis Stream Consumer — 后台 asyncio 任务，消费 Celery 推送的后处理数据
2. EventBus handlers — 注册到 "chat.completed" 事件，执行 DB 写入/WS 推送

跨进程桥接：
  Celery Worker → Redis Stream "postprocess_stream" → 本模块 Consumer → EventBus
"""
import asyncio
import json
import logging
from typing import Any, Dict

from app.chat_history import ChatHistoryManager
from app.core.config import get_settings
from app.core.events import bus
from app.domain.affection.service import AffectionService
from app.domain.memory.affective_service import AffectiveMemoryService
from app.domain.memory.vector_service import VectorMemoryService
from app.game_service import GameService
from app.infrastructure.redis import get_redis_client
from app.memory import MemoryService
from app.websocket_manager import manager

logger = logging.getLogger(__name__)

settings = get_settings()

# ==================== Redis Stream Consumer ====================


async def run_postprocess_consumer():
    """
    后台协程：消费 Redis Stream "postprocess_stream"。
    收到消息 → 反序列化 → bus.emit("chat.completed", data)。
    Celery Worker 写完 Stream 后，FastAPI 这边异步消费。
    """
    r = get_redis_client()
    if r is None:
        logger.error("Redis 未初始化，后处理 Consumer 退出")
        return

    group = "postprocess_workers"
    consumer = "fastapi_consumer_1"

    # 创建消费者组（幂等）
    try:
        await r.xgroup_create("postprocess_stream", group, mkstream=True)
    except Exception:
        pass  # 组已存在

    logger.info("后处理 Consumer 已启动 (group=%s consumer=%s)", group, consumer)

    while True:
        try:
            messages = await r.xreadgroup(
                groupname=group,
                consumername=consumer,
                streams={"postprocess_stream": ">"},
                count=1,
                block=1000,
            )
            if not messages:
                continue

            for _stream, msg_list in messages:
                for msg_id, msg_data in msg_list:
                    data_str = msg_data.get("data")
                    if not data_str:
                        await r.xack("postprocess_stream", group, msg_id)
                        continue

                    try:
                        task = json.loads(data_str)
                        logger.info(
                            "后处理: task=%s user=%s",
                            task.get("task_id", "?")[:8], task.get("user_id", "?")[:8],
                        )
                        # 发射到 EventBus → 所有 handler 并发执行
                        await bus.emit("chat.completed", task)
                    except Exception as e:
                        logger.error("后处理失败: %s", e)
                    finally:
                        await r.xack("postprocess_stream", group, msg_id)

        except asyncio.CancelledError:
            logger.info("后处理 Consumer 已取消")
            break
        except Exception as e:
            logger.error("后处理 Consumer 异常: %s", e, exc_info=True)
            await asyncio.sleep(1)


# ==================== EventBus Handlers ====================


@bus.on("chat.completed")
async def handle_store_chat_history(event: Dict[str, Any]) -> None:
    """存储聊天记录到数据库。"""
    user_id = event["user_id"]
    role_type = event["role_type"]
    user_input = event.get("user_input", "")
    ai_reply = event.get("ai_reply", "")

    if not user_input and not ai_reply:
        return

    try:
        chat_history = ChatHistoryManager()
        if user_input and not user_input.startswith("[ROLE_SELECT]"):
            await chat_history.add_message(user_id, role_type, "user", user_input)
        if ai_reply:
            await chat_history.add_message(user_id, role_type, "ai", ai_reply)
        logger.info("聊天记录已存储: user=%s", user_id[:8])
    except Exception as e:
        logger.error("存储聊天记录失败: %s", e)


@bus.on("chat.completed")
async def handle_affection_update(event: Dict[str, Any]) -> None:
    """更新好感度。"""
    try:
        affection_svc = AffectionService()
        delta = AffectionService.calculate_delta(
            event.get("user_input", ""),
            event.get("ai_reply", ""),
            event.get("emotion", {}),
        )
        await affection_svc.update(event["user_id"], event["role_type"], delta)
    except Exception as e:
        logger.error("好感度更新失败: %s", e)


@bus.on("chat.completed")
async def handle_memory_store(event: Dict[str, Any]) -> None:
    """存储语义记忆（ChromaDB）。"""
    user_input = event.get("user_input", "")
    if not user_input or user_input.startswith("[ROLE_SELECT]"):
        return

    try:
        memory_svc = MemoryService(settings)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            memory_svc.store,
            event["user_id"], user_input, event.get("ai_reply", ""),
            event.get("emotion", {}), event["role_type"],
        )
    except Exception as e:
        logger.error("语义记忆存储失败: %s", e)


@bus.on("chat.completed")
async def handle_extract_facts(event: Dict[str, Any]) -> None:
    """从对话中提取结构化事实。"""
    user_input = event.get("user_input", "")
    if not user_input or user_input.startswith("[ROLE_SELECT]"):
        return

    try:
        vms = VectorMemoryService(settings)
        affective_svc = AffectiveMemoryService(settings, vms)
        await affective_svc.extract_facts_from_conversation(
            event["user_id"], event["role_type"],
            user_input, event.get("ai_reply", ""),
        )
    except Exception as e:
        logger.error("事实提取失败: %s", e)


@bus.on("chat.completed")
async def handle_record_emotion(event: Dict[str, Any]) -> None:
    """记录情绪到情感层。"""
    emotion = event.get("emotion", {})
    if not emotion:
        return

    try:
        vms = VectorMemoryService(settings)
        affective_svc = AffectiveMemoryService(settings, vms)
        await affective_svc.record_emotion(
            event["user_id"], event["role_type"],
            emotion.get("label", "neutral"),
            emotion.get("score", 0.5),
            event.get("user_input", ""),
        )
    except Exception as e:
        logger.error("情感记录失败: %s", e)


@bus.on("chat.completed")
async def handle_milestone_check(event: Dict[str, Any]) -> None:
    """检查并添加关系里程碑。"""
    try:
        vms = VectorMemoryService(settings)
        affective_svc = AffectiveMemoryService(settings, vms)
        affection_svc = AffectionService()
        aff = await affection_svc.get(event["user_id"], event["role_type"])

        milestone_added = await affective_svc.check_and_add_milestones(
            event["user_id"], event["role_type"], aff.get("intimacy", 0),
        )
        if milestone_added and settings.USE_WEBSOCKET:
            await manager.send_personal_message(event["user_id"], {
                "type": "milestone",
                "content": "\U0001f389 你们的关系有了新的进展！",
            })
    except Exception as e:
        logger.error("里程碑检查失败: %s", e)


@bus.on("chat.completed")
async def handle_websocket_push(event: Dict[str, Any]) -> None:
    """通过 WebSocket 推送 AI 回复。"""
    if not settings.USE_WEBSOCKET:
        return

    try:
        await manager.send_personal_message(event["user_id"], {
            "type": "chat_reply",
            "task_id": event.get("task_id"),
            "reply": event.get("ai_reply", ""),
            "emotion": event.get("emotion", {}),
        })
        logger.info("WebSocket 推送成功: user=%s", event["user_id"][:8])
    except Exception as e:
        logger.error("WebSocket 推送失败: %s", e)


@bus.on("chat.completed")
async def handle_achievements(event: Dict[str, Any]) -> None:
    """更新成就进度。"""
    try:
        game_svc = GameService(settings)
        await game_svc.update_achievements(
            event["user_id"], event["role_type"],
            event.get("user_input", ""),
        )
    except Exception as e:
        logger.error("成就更新失败: %s", e)


@bus.on("chat.completed")
async def handle_cache_memory(event: Dict[str, Any]) -> None:
    """缓存结构化记忆到 Redis。"""
    try:
        vms = VectorMemoryService(settings)
        affective_svc = AffectiveMemoryService(settings, vms)
        await affective_svc.cache_structured_memory(
            event["user_id"], event["role_type"],
        )
    except Exception as e:
        logger.error("缓存结构化记忆失败: %s", e)
