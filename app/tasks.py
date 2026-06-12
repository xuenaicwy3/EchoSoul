import asyncio
import json
import threading
import redis
import psycopg
from celery import shared_task, current_task
from langgraph.checkpoint.postgres import PostgresSaver

from app.affective_memory_service import AffectiveMemoryService
from app.agent import EchoSoulAgent
from app.emotions import EmotionService
from app.memory import MemoryService
from app.affection import AffectionService
from app.config import Settings
import logging
settings = Settings()

logger = logging.getLogger(__name__)

_agent = None
_lock = threading.Lock()

def _build_agent():
    global _agent
    if _agent is None:
        with _lock:
            if _agent is None:
                emotion_svc = EmotionService(settings)
                affection_svc = AffectionService()
                memory_svc = MemoryService(settings)
                pg_conn = psycopg.connect(
                    "postgresql://echosoul:123456@localhost:5432/echosoul?sslmode=disable"
                )
                checkpointer = PostgresSaver(pg_conn)
                _agent = EchoSoulAgent(
                    settings,
                    emotion_svc=emotion_svc,
                    memory_svc=memory_svc,
                    affection_svc=affection_svc,
                    checkpointer=checkpointer
                )
                # 给 Agent 注入情感记忆服务
                _agent.affective_memory_svc = AffectiveMemoryService(settings)
    return _agent

@shared_task(name='process_chat')
def process_chat(task_payload: dict) -> dict:
    """
     处理聊天任务（同步任务，内部用 asyncio.run 调用异步 Agent）
     """
    # ========== 测试模式：全部使用假数据，不调 AI ==========
    if settings.TEST_MODE:
        user_id = task_payload["user_id"]
        role_type = task_payload.get("role_type", "温柔贤淑型")
        # 固定回复，模拟 AI 输出
        fake_reply = "（测试模式）这是假回复，用于高并发压测。"
        fake_emotion = {"label": "neutral", "score": 0.9}

        # 推送后处理数据到 Redis Stream，与真实流程完全一致
        r = redis.Redis.from_url(settings.REDIS_URL)
        postprocess_data = {
            "task_id": current_task.request.id,  # 当前任务 ID
            "user_id": user_id,
            "role_type": role_type,
            "user_input": task_payload.get("user_input", ""),
            "ai_reply": fake_reply,
            "emotion": fake_emotion,
        }
        r.xadd("postprocess_stream", {"data": json.dumps(postprocess_data)})

        return {
            "reply": fake_reply,
            "emotion": fake_emotion,
            "role": role_type
        }

    # ========== 正常模式：真实 AI 调用 ==========
    # 1. 从 task_payload 里取出用户信息、消息、角色、好感度等
    task_id = task_payload.get("task_id")
    user_id = task_payload["user_id"]
    role_type = task_payload["role_type"]
    user_input = task_payload["user_input"]
    preset_greeting = task_payload.get("preset_greeting")
    aff_info = task_payload.get("aff_info", "")
    unlock_info = task_payload.get("unlock_info", "")
    thread_id = task_payload["thread_id"]
    need_regenerate = task_payload.get("need_regenerate", False)
    regenerate_context = task_payload.get("regenerate_context")

    # 2. 初始化 LangGraph 的状态（state）
    init_state = {
        "user_id": user_id,
        "user_input": user_input,
        "role_type": role_type,
        "emotion": {},
        "memory_text": "",
        "final_response": preset_greeting,
        "need_regenerate": need_regenerate,
        "regenerate_context": regenerate_context,
        "aff_info": aff_info,
        "unlock_info": unlock_info,
    }
    config = {"configurable": {"thread_id": thread_id}}

    # 3. 构建 Agent状态图（里面跑 LangGraph 的 4 个节点）
    agent = _build_agent()  # 单例模式，避免重复创建

    # ---- 获取结构化记忆（从 Redis 缓存） ----
    structured_mem = ""
    try:
        r = redis.Redis.from_url(settings.REDIS_URL)
        cached = r.get(f"structured_memory:{user_id}:{role_type}")
        if cached:
            structured_mem = cached.decode('utf-8')
            logger.info(f"[Celery] 成功读取结构化记忆缓存 (长度={len(structured_mem)})")
            # logger.info(f"从 Redis 获取结构化记忆缓存成功 structured_mem={structured_mem}")
        else:
            logger.info("[Celery] Redis 中无结构化记忆缓存，使用空记忆")
    except Exception as e:
        logger.error(f"[Celery] 读取结构化记忆缓存失败: {e}")

    # 获取 Chroma 语义记忆（同步）
    chroma_mem = agent.memory_svc.retrieve(user_id=user_id, query=task_payload["user_input"], role_type=role_type)

    # 组合记忆并写入 state
    parts = [chroma_mem, structured_mem]
    init_state["memory_text"] = "\n".join([p for p in parts if p])

    # 使用同步 invoke，确保检查点正常工作
    result = agent.invoke(init_state, config)  # 同步调用，内部执行完返回结果

    # 推送后处理数据到 Redis Stream（使用同步客户端）
    # Redis Stream 是一个消息队列，支持多消费者、消息持久化、确认机制（XACK）。这里用它来传递后处理数据。
    # 4. 任务完成后，不直接写数据库，而是把结果推送到 Redis Stream
    r = redis.Redis.from_url(settings.REDIS_URL)
    postprocess_data = {
        "task_id": current_task.request.id,  # 当前任务 ID
        "user_id": user_id,
        "role_type": role_type,
        "user_input": user_input,
        "ai_reply": result.get("final_response", ""),
        "emotion": result.get("emotion", {}),
    }
    r.xadd("postprocess_stream", {"data": json.dumps(postprocess_data)})

    # 5. 返回结果给 Celery（前端轮询时会拿到）
    return {
        "reply": result.get("final_response", ""),
        "emotion": result.get("emotion", {}),
        "role": result.get("role_type", "")
    }