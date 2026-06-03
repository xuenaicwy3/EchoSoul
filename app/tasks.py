import json
import threading
from celery import shared_task
import redis
import psycopg
from langgraph.checkpoint.postgres import PostgresSaver

from app.agent import EchoSoulAgent
from app.emotions import EmotionService
from app.memory import MemoryService
from app.affection import AffectionService
from app.config import Settings

settings = Settings()

# 缓存 Agent 实例（线程安全）
_agent = None
_lock = threading.Lock()

def _build_agent():
    global _agent
    if _agent is None:
        with _lock:
            if _agent is None:
                emotion_svc = EmotionService(settings)
                memory_svc = MemoryService(settings)
                affection_svc = AffectionService()
                # 使用 psycopg (v3) 同步连接
                pg_conn = psycopg.connect(
                    "postgresql://echosoul:123456@localhost:5432/echosoul?sslmode=disable"
                )
                checkpointer = PostgresSaver(pg_conn)
                _agent = EchoSoulAgent(
                    settings, emotion_svc, memory_svc, affection_svc,
                    checkpointer=checkpointer
                )
    return _agent

@shared_task(name='process_chat')
def process_chat(task_payload: dict) -> dict:
    """
    处理聊天任务
    参数 task_payload 是字典，由 Celery 自动反序列化
    """
    # 直接使用字典，无需 json.loads
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

    agent = _build_agent()
    result = agent.invoke(init_state, config)

    # 将后处理任务推送到 Redis Stream（使用同步客户端）
    r = redis.Redis.from_url(settings.REDIS_URL)
    postprocess_data = {
        "user_id": user_id,
        "role_type": role_type,
        "user_input": user_input,
        "ai_reply": result.get("final_response", ""),
        "emotion": result.get("emotion", {}),
    }
    r.xadd("postprocess_stream", {"data": json.dumps(postprocess_data)})

    return {
        "reply": result.get("final_response", ""),
        "emotion": result.get("emotion", {}),
        "role": result.get("role_type", "")
    }