"""
Celery 异步任务 — 生产级高并发设计。

process_chat: 发布到 Celery Worker，不阻塞 FastAPI。
- 重试 2 次 + 5s 退避
- 60s 硬超时 / 50s 软超时
- AI 调用失败自动重试
- 完成后通过 Redis Stream 通知 FastAPI 执行后处理
"""
import asyncio
import json
import logging
import threading

import psycopg
import redis
from celery import shared_task, current_task
from celery.exceptions import SoftTimeLimitExceeded
from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.affective_memory_service import AffectiveMemoryService
from app.agent import EchoSoulAgent
from app.core.config import get_settings
from app.domain.emotion.service import EmotionService
from app.domain.affection.service import AffectionService
from app.memory import MemoryService
from app.domain.memory.vector_service import VectorMemoryService

logger = logging.getLogger(__name__)

settings = get_settings()

# Celery Worker 中 async engine 的初始化标志
_async_engine_initialized = False

# ==================== Agent 单例（线程安全） ====================

_agent: EchoSoulAgent | None = None
_lock = threading.Lock()


def _build_agent() -> EchoSoulAgent:
    """构建 Agent 单例，线程安全。同时初始化 async engine 供 VectorMemoryService 使用。"""
    global _agent, _async_engine_initialized

    # ---- 初始化 async 数据库引擎（Celery Worker 进程首次需要） ----
    if not _async_engine_initialized:
        from app.infrastructure import database as db_module
        if db_module._async_session_factory is None:
            engine = create_async_engine(
                settings.DATABASE_URL,
                echo=False,
                poolclass=NullPool,  # Celery threads 模式：用完即弃，避免 Event loop is closed
            )
            db_module._async_session_factory = async_sessionmaker(
                engine, expire_on_commit=False, autoflush=False,
            )
            logger.info("[Celery] async engine 已初始化 (pool=5)")
        _async_engine_initialized = True

    if _agent is None:
        with _lock:
            if _agent is None:
                emotion_svc = EmotionService()
                affection_svc = AffectionService()
                memory_svc = MemoryService(settings)

                # PG Checkpointer（同步连接）
                db_url = settings.DATABASE_URL
                sync_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
                if "?" in sync_url:
                    sync_url = sync_url.split("?")[0]
                pg_conn = psycopg.connect(sync_url)
                checkpointer = PostgresSaver(pg_conn)

                _agent = EchoSoulAgent(
                    settings,
                    emotion_svc=emotion_svc,
                    memory_svc=memory_svc,
                    affection_svc=affection_svc,
                    checkpointer=checkpointer,
                )
                # 注入情感记忆服务
                vms = VectorMemoryService(settings)
                _agent.affective_memory_svc = AffectiveMemoryService(settings, vms)
                logger.info("[Celery] Agent 单例已创建")
    return _agent


# ==================== 核心任务 ====================


@shared_task(
    name="process_chat",
    bind=True,
    max_retries=2,
    default_retry_delay=5,
    autoretry_for=(Exception,),
    task_time_limit=60,
    task_soft_time_limit=50,
    acks_late=True,
    task_reject_on_worker_lost=True,
    rate_limit="4/m",
    result_expires=600,
)
def process_chat(self, task_payload: dict) -> dict:
    """
    异步处理聊天任务。

    管线：
    1. 从 Redis 取结构化记忆缓存
    2. 从 ChromaDB 取语义记忆
    3. Agent.invoke() → LangGraph 状态图 (~5s)
    4. 结果写入 Redis (chat_result:{task_id})
    5. 后处理数据推送 Redis Stream → FastAPI EventBus 消费
    6. 返回结果
    """
    task_id = self.request.id
    user_id = task_payload["user_id"]
    role_type = task_payload.get("role_type", "温柔贤淑型")
    user_input = task_payload.get("user_input", "")
    thread_id = task_payload.get("thread_id", user_id)

    logger.info(
        "[Celery task=%s] 开始处理: user=%s role=%s msg=%s",
        task_id[:8], user_id[:8], role_type, user_input[:30],
    )

    # ---- 1. 获取结构化记忆缓存 ----
    structured_mem = ""
    try:
        r = redis.Redis.from_url(settings.REDIS_URL)
        cached = r.get(f"structured_memory:{user_id}:{role_type}")
        if cached:
            structured_mem = cached.decode("utf-8") if isinstance(cached, bytes) else cached
            logger.info("[Celery task=%s] 结构化记忆缓存 (len=%d)", task_id[:8], len(structured_mem))
    except Exception as e:
        logger.error("[Celery task=%s] 读取缓存失败: %s", task_id[:8], e)

    # ---- 2. 获取 Chroma 语义记忆 ----
    chroma_mem = ""
    try:
        agent = _build_agent()
        chroma_mem = agent.memory_svc.retrieve(
            user_id=user_id, query=user_input, role_type=role_type,
        )
        logger.info("[Celery task=%s] Chroma 语义记忆 (len=%d)", task_id[:8], len(chroma_mem))
    except Exception as e:
        logger.error("[Celery task=%s] Chroma 检索失败: %s", task_id[:8], e)

    # ---- 3. 组合记忆 → Agent State ----
    memory_text = "\n".join(filter(None, [chroma_mem, structured_mem]))

    init_state = {
        "user_id": user_id,
        "user_input": user_input,
        "role_type": task_payload.get("role_type"),
        "emotion": {},
        "memory_text": memory_text,
        "final_response": task_payload.get("preset_greeting"),
        "need_regenerate": task_payload.get("need_regenerate", False),
        "regenerate_context": task_payload.get("regenerate_context"),
        "aff_info": task_payload.get("aff_info", ""),
        "unlock_info": task_payload.get("unlock_info", ""),
    }
    config = {"configurable": {"thread_id": thread_id}}

    # ---- 4. Agent.invoke() ----
    try:
        logger.info("[Celery task=%s] Agent.invoke 开始...", task_id[:8])
        agent = _build_agent()
        result = agent.invoke(init_state, config)
        ai_reply = result.get("final_response", "")
        emotion = result.get("emotion", {})
        logger.info(
            "[Celery task=%s] Agent.invoke 完成: reply_len=%d emotion=%s",
            task_id[:8], len(ai_reply), emotion.get("label", "unknown"),
        )
    except SoftTimeLimitExceeded:
        logger.error("[Celery task=%s] 软超时! 50s 内未完成", task_id[:8])
        raise
    except Exception as e:
        logger.error("[Celery task=%s] Agent 调用失败: %s", task_id[:8], e)
        # 可重试异常 → 自动重试
        raise

    # ---- 5. 结果写入 Redis ----
    try:
        r = redis.Redis.from_url(settings.REDIS_URL)
        result_data = {
            "reply": ai_reply,
            "emotion": emotion,
            "role": result.get("role_type", ""),
        }
        r.setex(f"chat_result:{task_id}", 600, json.dumps(result_data))
        logger.info("[Celery task=%s] 结果已写入 Redis", task_id[:8])
    except Exception as e:
        logger.error("[Celery task=%s] Redis 写入失败: %s", task_id[:8], e)

    # ---- 6. 后处理数据推送 Redis Stream ----
    try:
        postprocess_data = {
            "task_id": task_id,
            "user_id": user_id,
            "role_type": role_type,
            "user_input": user_input,
            "ai_reply": ai_reply,
            "emotion": emotion,
        }
        r.xadd("postprocess_stream", {"data": json.dumps(postprocess_data)})
        logger.info("[Celery task=%s] 后处理数据已推送 Stream", task_id[:8])
    except Exception as e:
        logger.error("[Celery task=%s] Stream 推送失败: %s", task_id[:8], e)

    logger.info("[Celery task=%s] 完成", task_id[:8])
    return result_data
