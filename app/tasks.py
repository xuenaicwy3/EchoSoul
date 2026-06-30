"""
Celery 异步任务 — EchoSoul Harness 架构集成。

Harness 三层协作:
  Context 层（数据准备）→ Harness 层（Agent 编排）→ Model 层（LLM 调用）

process_chat:
  1. 构建 HarnessContext（Context 层：记忆/好感度/会话状态）
  2. AgentHarness.invoke()（Harness 层：ReAct + Function Calling + Skills + MCP + 中断）
  3. 结果写入 Redis + 推送 Stream
"""
import json
import logging
import threading

import redis
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.harness.context import HarnessContext, SessionContext, MemoryContext, RelationshipContext
from app.harness.agent import AgentHarness

logger = logging.getLogger(__name__)

settings = get_settings()
_async_engine_initialized = False

# ==================== Harness 单例 ====================

_harness: AgentHarness | None = None
_lock = threading.Lock()


def _init_async_engine():
    global _async_engine_initialized
    if not _async_engine_initialized:
        from app.infrastructure import database as db_module
        if db_module._async_session_factory is None:
            engine = create_async_engine(
                settings.DATABASE_URL, echo=False, poolclass=NullPool,
                pool_recycle=3600, pool_pre_ping=True)
            db_module._async_session_factory = async_sessionmaker(
                engine, expire_on_commit=False, autoflush=False)
            logger.info("[Celery] async engine 已初始化")
        _async_engine_initialized = True


def get_harness() -> AgentHarness:
    """获取 AgentHarness 单例（线程安全）。

    Harness 封装了 Context → Harness → Model 三层的完整生命周期。
    """
    global _harness
    _init_async_engine()

    if _harness is None:
        with _lock:
            if _harness is None:
                # PG Checkpointer
                import psycopg
                db_url = settings.DATABASE_URL
                sync_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
                if "?" in sync_url:
                    sync_url = sync_url.split("?")[0]
                pg_conn = psycopg.connect(sync_url)
                checkpointer = PostgresSaver(pg_conn)

                # 构建 Harness（Context/Harness/Model 三层自动初始化）
                _harness = AgentHarness(checkpointer=checkpointer)
                _harness.setup() # 启动时初始化
                logger.info("[Celery] AgentHarness 单例已创建: %s", _harness.get_stats())
    return _harness


# ==================== Context 层构建（数据准备） ====================


def _build_context(task_payload: dict) -> HarnessContext:
    """Context 层：聚合记忆/好感度/会话数据。

    此函数是 Context 层的唯一入口。
    变 Context 数据只需改此函数，不动 Harness 代码。
    """
    user_id = task_payload["user_id"]
    role_type = task_payload.get("role_type", "温柔贤淑型")
    user_input = task_payload.get("user_input", "")

    # ---- MemoryContext ----
    memory = MemoryContext()

    # 结构化记忆缓存 (Redis)
    try:
        r = redis.Redis.from_url(settings.REDIS_URL)
        cached = r.get(f"structured_memory:{user_id}:{role_type}")
        if cached:
            memory.structured_mem = cached.decode("utf-8") if isinstance(cached, bytes) else cached
    except Exception as e:
        logger.error("[Context] Redis 读取失败: %s", e)

    # ChromaDB 语义记忆由 Agent 图内的 memory_node 统一检索，避免重复查询

    # ---- RelationshipContext ----
    relationship = RelationshipContext()
    try:
        from app.domain.affection.service import AffectionService
        aff_svc = AffectionService()
        import asyncio
        aff = asyncio.run(aff_svc.get(user_id, role_type))
        unlocks = asyncio.run(aff_svc.get_unlock_state(user_id, role_type))
        relationship = RelationshipContext(
            intimacy=aff.get("intimacy", 10),
            trust=aff.get("trust", 10),
            fun=aff.get("fun", 10),
            growth=aff.get("growth", 10),
            level=unlocks.get("level", 0),
            style_modifier=unlocks.get("style_modifier", ""),
            story_unlocked=unlocks.get("story_unlocked", False),
        )
    except Exception as e:
        logger.error("[Context] 好感度查询失败: %s", e)

    # ---- SessionContext ----
    session = SessionContext(
        user_id=user_id,
        role_type=role_type,
        user_input=user_input,
        need_regenerate=task_payload.get("need_regenerate", False),
        regenerate_context=task_payload.get("regenerate_context"),
        active_skills=task_payload.get("active_skills", []),
    )

    return HarnessContext(session=session, memory=memory, relationship=relationship)


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
    """异步处理聊天任务 — Harness 三层架构：Context → Harness → Model。

    Context 层: _build_context()    → 聚合记忆/好感度/会话数据
    Harness 层: harness.invoke()    → ReAct + Function Calling + Skills + MCP + 中断
    Model 层:   harness.model_provider  → chat=DeepSeek emotion=Qwen embed=text-embedding-v4
    """
    task_id = self.request.id
    user_id = task_payload["user_id"]
    user_input = task_payload.get("user_input", "")

    logger.info(
        "[Celery task=%s] START: user=%s msg=%s",
        task_id[:8], user_id[:8], user_input[:30],
    )

    _init_async_engine()

    # ---- 1. Context 层：聚合数据 ----
    context = _build_context(task_payload)

    # ---- 2. Harness 层：Agent 编排 ----
    harness = get_harness()

    # ---- 3. Model 层：LLM 实例 ----
    model = harness.model_provider  # ModelProvider(chat=deepseek-v4-pro, emotion=qwen3.7-plus)
    logger.debug("[Celery] Model: chat=%s", model.config.chat_model)

    thread_id = task_payload.get("thread_id", user_id)

    try:
        result = harness.invoke(context, thread_id)
    except SoftTimeLimitExceeded:
        logger.error("[Celery task=%s] 软超时 50s!", task_id[:8])
        raise
    except Exception as e:
        logger.error("[Celery task=%s] 执行失败: %s", task_id[:8], e)
        raise

    # ---- 结果处理 ----
    if result.get("status") == "pending_approval":
        # 中断：Agent 暂停等待审批
        logger.info("[Celery task=%s] INTERRUPT: %s", task_id[:8],
                    [t.get("name") for t in result.get("interrupt", {}).get("sensitive_tools", [])])
        _store_result(task_id, result)
        return result

    ai_reply = result.get("reply", "")
    emotion = result.get("emotion", {})
    tools = result.get("tools", [])

    # 写入 Redis
    _store_result(task_id, {
        "reply": ai_reply,
        "emotion": emotion,
        "role": task_payload.get("role_type", ""),
        "tools": tools,
    })

    # 推送后处理 Stream
    _push_to_stream(task_id, user_id, task_payload.get("role_type", ""),
                    user_input, ai_reply, emotion, tools)

    logger.info("[Celery task=%s] DONE: reply_len=%d tools=%d",
                task_id[:8], len(ai_reply), len(tools))
    return {"reply": ai_reply, "emotion": emotion, "tools": tools}


# ==================== SSE 流式任务（Celery Worker → Redis pub/sub） ====================


@shared_task(
    name="process_chat_stream",
    bind=True,
    max_retries=1,
    default_retry_delay=3,
    autoretry_for=(Exception,),
    task_time_limit=90,
    task_soft_time_limit=80,
    acks_late=True,
    task_reject_on_worker_lost=True,
    result_expires=300,
)
def process_chat_stream(self, task_payload: dict) -> dict:
    """Harness 三层架构：Context → Harness → Model。

    Context 层: _build_context()    → 聚合记忆/好感度
    Harness 层: graph.stream()     → ReAct + FC + Skills + MCP + 中断
    Model 层:   model_provider     → chat=DeepSeek emotion=Qwen

    Celery Worker 逐 Token 流式 → Redis pub/sub → FastAPI SSE。

    使用 LangGraph graph.astream_events(version="v2") 官方流式 API，
    捕获 on_chat_model_stream 事件实现真正的逐 token 推送。
    LLM 每生成一个 token 立即 publish 到 Redis，前端逐字渲染。
    """

    task_id = self.request.id
    user_id = task_payload["user_id"]
    user_input = task_payload.get("user_input", "")

    logger.info("[CeleryStream task=%s] START: user=%s msg=%s",
                task_id[:8], user_id[:8], user_input[:30])

    _init_async_engine()

    # ---- 1. Context 层 ----
    context = _build_context(task_payload)

    # ---- 2. Harness 层 ----
    harness = get_harness()

    # ---- 3. Model 层 ----
    model = harness.model_provider  # ModelProvider(chat=deepseek-v4-pro, emotion=qwen3.7-plus)
    logger.debug("[CeleryStream] Model: chat=%s", model.config.chat_model)

    thread_id = task_payload.get("thread_id", user_id)

    try:
        r = redis.Redis.from_url(settings.REDIS_URL)
        channel = f"chat_stream:{task_id}"

        def _pub(event: str, data: dict):
            r.publish(channel, json.dumps({"event": event, "data": data}, ensure_ascii=False))

        accumulated = ""
        first_token = False
        emitted_nodes: set = set()

        # graph.stream() 官方 sync API —— 遇 interrupt() 自动暂停
        for chunk in harness.stream(context, thread_id):
            for tc in chunk.get("tool_calls", []):
                _pub("tool_call", {"name": tc.get("name", ""), "args": tc.get("args", {})})
            for te in chunk.get("tool_executions", []):
                _pub("tool_result", {"tool": te.get("tool_name", ""),
                                     "success": te.get("success", True),
                                     "preview": str(te.get("result_preview", ""))[:200]})
            nodes = _detect_nodes(chunk)
            for node in nodes - emitted_nodes:
                emitted_nodes.add(node)
                _pub("node", {"name": node})
            reply = chunk.get("final_response", "")
            if reply and reply != accumulated:
                if not first_token:
                    first_token = True
                    logger.info("[CeleryStream task=%s] 首 Token 已推送", task_id[:8])
                delta = reply[len(accumulated):]
                accumulated = reply
                _pub("token", {"content": delta})

        # 官方中断检测：stream() 结束后查 get_state().next
        _state = harness.get_state(thread_id)
        if _state.next:
            pending_tools = list(chunk.get("tool_calls", []))
            logger.info("[CeleryStream task=%s] ⏸ 中断: next=%s tools=%s",
                        task_id[:8], _state.next,
                        [t.get("name") for t in pending_tools])
            _pub("interrupt", {"message": "敏感工具等待审批", "thread_id": thread_id,
                                "sensitive_tools": pending_tools})
        else:
            _pub("done", {"reply": accumulated, "emotion": {}})
        logger.info("[CeleryStream task=%s] DONE: reply_len=%d tokens=%d",
                    task_id[:8], len(accumulated), len(accumulated))

    except Exception as e:
        logger.error("[CeleryStream task=%s] 失败: %s", task_id[:8], e, exc_info=True)
        try:
            r = redis.Redis.from_url(settings.REDIS_URL)
            r.publish(f"chat_stream:{task_id}", json.dumps({"event": "error", "data": {"message": str(e)}}))
        except:
            pass
        raise

    return {"reply": accumulated, "status": "complete"}


@shared_task(
    name="process_chat_resume",
    bind=True,
    max_retries=1,
    default_retry_delay=3,
    autoretry_for=(Exception,),
    task_time_limit=60,
    task_soft_time_limit=50,
    acks_late=True,
    task_reject_on_worker_lost=True,
    result_expires=300,
)
def process_chat_resume(self, task_payload: dict) -> dict:
    """Celery Worker 中断恢复 → Redis pub/sub → FastAPI SSE。

    从中断点 resume，继续执行审批通过的工具，流式返回结果。
    """
    task_id = task_payload.get("task_id", self.request.id)
    thread_id = task_payload.get("thread_id", "")
    resume_value = task_payload.get("resume_value", {})

    logger.info("[CeleryResume task=%s] START: thread=%s approved=%s",
                task_id[:8], thread_id[:8], resume_value.get("approved", []))

    harness = get_harness()

    try:
        r = redis.Redis.from_url(settings.REDIS_URL)
        channel = f"chat_stream:{task_id}"

        def _pub(event: str, data: dict):
            r.publish(channel, json.dumps({"event": event, "data": data}, ensure_ascii=False))

        accumulated = ""
        config = {"configurable": {"thread_id": thread_id}}

        for chunk in harness.agent.resume(resume_value, config):
            reply = chunk.get("final_response", "")
            if reply and reply != accumulated:
                delta = reply[len(accumulated):]
                accumulated = reply
                _pub("token", {"content": delta})

            for te in chunk.get("tool_executions", []):
                _pub("tool_result", {"tool": te.get("tool_name", ""),
                                     "success": te.get("success", True)})

        _pub("done", {"reply": accumulated, "emotion": {}})
        logger.info("[CeleryResume task=%s] DONE: reply_len=%d", task_id[:8], len(accumulated))

    except Exception as e:
        logger.error("[CeleryResume task=%s] 失败: %s", task_id[:8], e, exc_info=True)
        try:
            r = redis.Redis.from_url(settings.REDIS_URL)
            r.publish(f"chat_stream:{task_id}", json.dumps({"event": "error", "data": {"message": str(e)}}))
        except:
            pass
        raise

    return {"reply": accumulated, "status": "complete"}


def _detect_nodes(chunk: dict) -> set:
    """从状态快照推断活跃节点。"""
    nodes = set()
    if chunk.get("role_type"):
        nodes.add("select_role")
    if chunk.get("emotion"):
        nodes.add("emotion")
    if chunk.get("memory_text"):
        nodes.add("memory")
    if chunk.get("final_response"):
        nodes.add("generate")
    if chunk.get("tool_calls"):
        nodes.add("router")
    if chunk.get("tool_executions"):
        nodes.add("tool_exec")
    return nodes


# ==================== 辅助 ====================


def _store_result(task_id: str, data: dict) -> None:
    try:
        r = redis.Redis.from_url(settings.REDIS_URL)
        r.setex(f"chat_result:{task_id}", 600, json.dumps(data, ensure_ascii=False))
    except Exception as e:
        logger.error("[Celery task=%s] Redis 写入失败: %s", task_id[:8], e)


def _push_to_stream(task_id, user_id, role_type, user_input, ai_reply, emotion, tools):
    try:
        r = redis.Redis.from_url(settings.REDIS_URL)
        r.xadd("postprocess_stream", {"data": json.dumps({
            "task_id": task_id, "user_id": user_id, "role_type": role_type,
            "user_input": user_input, "ai_reply": ai_reply, "emotion": emotion,
            "tool_executions": tools,
        }, ensure_ascii=False)})
    except Exception as e:
        logger.error("[Celery task=%s] Stream 推送失败: %s", task_id[:8], e)
