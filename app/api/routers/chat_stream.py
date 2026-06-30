"""
SSE 流式对话端点 — Celery Worker 执行 + Redis pub/sub 桥接。

架构（字节 DeerFlow 生产模式）:
  Frontend → POST /chat/stream → FastAPI → Celery.send_task()
  Celery Worker → Agent.stream() → redis.publish("chat_stream:{id}", json)
  FastAPI → redis.asyncio pub/sub → SSE → Frontend

FastAPI 不直接跑 Agent，零阻塞，高并发。
"""
import asyncio
import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.models.schemas import ChatRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])
settings = get_settings()


@router.post("/stream")
async def chat_stream(
    req: ChatRequest,
    current_user: str = Depends(get_current_user),
):
    """SSE 流式对话端点（Celery Worker + Redis pub/sub）。

    请求体: {"message": "你好", "role_type": "日系动漫型"}

    流程:
      1. 发布 Celery 任务 process_chat_stream
      2. 订阅 Redis pub/sub channel "chat_stream:{task_id}"
      3. 每个消息转为 SSE 事件推送给前端
      4. "done" 事件到达后关闭流
    """
    user_id = current_user
    logger.info("[SSE-STREAM] ===== START: user=%s msg=%s =====", user_id[:8], req.message[:30])

    import redis.asyncio as aioredis

    # 1. 先订阅 Redis（必须在 Celery 任务发布之前，避免丢消息）
    r = aioredis.from_url(settings.REDIS_URL,
                          socket_timeout=None,
                          socket_connect_timeout=10,
                          socket_keepalive=True)
    pubsub = r.pubsub()

    # 生成 task_id 用于 channel 名称
    from app.task_registry import ChatTaskPayload, celery_app
    from uuid import uuid4
    task_id = str(uuid4())
    channel = f"chat_stream:{task_id}"
    await pubsub.subscribe(channel)
    logger.info("[SSE-STREAM] Redis sub 已订阅: %s", channel)

    # 2. 发布 Celery 任务（订阅先注册，确保不丢消息）
    payload = ChatTaskPayload(
        user_id=user_id,
        role_type=req.role_type,
        user_input=req.message,
        thread_id=user_id,
        enable_tools=True,
    )
    celery_app.send_task("process_chat_stream", args=[payload.model_dump()], task_id=task_id)
    logger.info("[SSE-STREAM] Celery task=%s 已发布", task_id[:8])

    async def event_generator():
        try:
            first_token = False

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue

                data_str = message["data"]
                if isinstance(data_str, bytes):
                    data_str = data_str.decode("utf-8")

                try:
                    msg = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                event_type = msg.get("event", "")
                data = msg.get("data", {})

                if event_type == "token":
                    if not first_token:
                        first_token = True
                        logger.info("[SSE-STREAM] 首 Token")
                    yield _sse("token", data)

                elif event_type == "node":
                    yield _sse("node", data)

                elif event_type == "tool_call":
                    yield _sse("tool_call", data)

                elif event_type == "tool_result":
                    yield _sse("tool_result", data)

                elif event_type == "interrupt":
                    yield _sse("interrupt", data)

                elif event_type == "pending_approval":
                    yield _sse("pending_approval", data)
                    break

                elif event_type == "done":
                    yield _sse("final", data)
                    break

                elif event_type == "error":
                    yield _sse("error", data)
                    break

            try:
                await pubsub.unsubscribe(channel)
                await r.close()
            except Exception:
                pass  # 连接已关闭时静默忽略

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("[SSE-STREAM] 异常: %s", e, exc_info=True)
            yield _sse("error", {"message": str(e)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/resume")
async def chat_resume(
    req: dict,
    current_user: str = Depends(get_current_user),
):
    """SSE 中断恢复端点。

    请求体: {"thread_id": "...", "approved": ["save_memory"], "rejected": []}

    用户审批后，从中断点恢复 Agent 执行，流式返回结果。
    """
    import redis.asyncio as aioredis
    from uuid import uuid4

    thread_id = req.get("thread_id", "")
    approved = req.get("approved", [])
    rejected = req.get("rejected", [])
    resume_value = {"approved": approved, "rejected": rejected}

    logger.info("[SSE-RESUME] thread=%s approved=%s rejected=%s",
                thread_id[:8] if thread_id else "?", approved, rejected)

    task_id = str(uuid4())
    channel = f"chat_stream:{task_id}"

    r = aioredis.from_url(settings.REDIS_URL,
                          socket_timeout=None,
                          socket_connect_timeout=10,
                          socket_keepalive=True)
    pubsub = r.pubsub()
    await pubsub.subscribe(channel)

    # 发布 Celery 恢复任务
    from app.task_registry import celery_app
    celery_app.send_task("process_chat_resume", args=[{
        "thread_id": thread_id,
        "resume_value": resume_value,
        "task_id": task_id,
    }], task_id=task_id)

    async def event_generator():
        try:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                data_str = message["data"]
                if isinstance(data_str, bytes):
                    data_str = data_str.decode("utf-8")
                try:
                    msg = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                event_type = msg.get("event", "")
                data = msg.get("data", {})
                if event_type == "token":
                    yield _sse("token", data)
                elif event_type == "done":
                    yield _sse("final", data)
                    break
                elif event_type == "error":
                    yield _sse("error", data)
                    break
            await pubsub.unsubscribe(channel)
            await r.close()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("[SSE-RESUME] 异常: %s", e, exc_info=True)
            yield _sse("error", {"message": str(e)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
