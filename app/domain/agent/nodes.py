"""
LangGraph 状态图节点函数。

每个节点接收 AgentState，返回更新后的 AgentState。
generate_node 完成后通过 EventBus 发射 "chat.completed" 事件，
解耦后续副作用操作（存历史、更新好感度、推 WebSocket 等）。
"""
import asyncio
import logging
from typing import Optional

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import get_settings
from app.core.events import bus
from app.domain.agent.prompts import PromptFactory
from app.domain.emotion.service import EmotionService
from app.domain.memory.vector_service import VectorMemoryService
from app.domain.roles.catalog import RoleCatalog
from app.models.schemas import AgentState

logger = logging.getLogger(__name__)

settings = get_settings()

# ---- LLM 实例（模块级复用） ----
_llm: Optional["BaseChatModel"] = None
_vector_memory_svc: Optional[VectorMemoryService] = None


def _get_llm() -> "BaseChatModel":
    global _llm
    if _llm is None:
        _llm = init_chat_model(
            model=settings.LLM_MODEL,
            model_provider="openai",
            temperature=0.8,
            max_tokens=512,
            api_key=settings.DASHSCOPE_API_KEY,
            base_url=settings.DASHSCOPE_BASE_URL,
        )
    return _llm


def _get_vector_memory() -> VectorMemoryService:
    global _vector_memory_svc
    if _vector_memory_svc is None:
        _vector_memory_svc = VectorMemoryService(settings)
    return _vector_memory_svc


# ==================== 节点函数 ====================


def select_role_node(state: AgentState, emotion_svc: EmotionService) -> AgentState:
    """角色选择节点：首次对话时分配默认角色。"""
    user_msg = state.get("user_input", "")
    if user_msg.startswith("[ROLE_SELECT]"):
        logger.info("[select_role] 角色已由 HTTP 层预设, role_type=%s", state.get("role_type"))
        return state
    if not state.get("role_type"):
        default = "温柔贤淑型"
        greeting = RoleCatalog.get_role(default).greeting
        logger.info("[select_role] 使用默认角色: %s", default)
        state["role_type"] = default
        state["final_response"] = greeting
    return state


def emotion_node(state: AgentState, emotion_svc: EmotionService) -> AgentState:
    """情绪分析节点：分析用户消息情绪。"""
    user_msg = state.get("user_input", "")
    if settings.TEST_MODE or not user_msg:
        state["emotion"] = {"label": "neutral", "score": 0.5}
        return state
    emotion = emotion_svc.analyze(user_msg)
    state["emotion"] = emotion
    return state


def memory_node(state: AgentState, emotion_svc: EmotionService) -> AgentState:
    """记忆检索节点：从向量库检索相关历史记忆。"""
    user_msg = state.get("user_input", "")
    if not user_msg or user_msg.startswith("[ROLE_SELECT]") or settings.TEST_MODE:
        return state

    user_id = state.get("user_id", "")
    role_type = state.get("role_type", "")
    if not user_id or not role_type:
        return state

    try:
        vms = _get_vector_memory()
        vms.ensure_loaded(user_id, role_type)

        # 获取会话轮数
        try:
            from app.chat_history import ChatHistoryManager
            rounds = asyncio.run(ChatHistoryManager().count_rounds(user_id, role_type))
        except Exception:
            rounds = 0

        layers = vms.smart_retrieve(user_id, role_type, user_msg, rounds)
        vector_text = VectorMemoryService.format_layers_for_prompt(layers)

        if not vector_text and rounds > 0:
            logger.info("路由检索无命中，退回全量检索: user=%s rounds=%d", user_id, rounds)
            layers = vms.retrieve_all_layers(user_id, role_type, user_msg)
            vector_text = VectorMemoryService.format_layers_for_prompt(layers)

        if vector_text:
            existing = state.get("memory_text", "")
            state["memory_text"] = (existing + "\n\n" + vector_text) if existing else vector_text
            logger.info("向量检索注入: chars=%d rounds=%d", len(state["memory_text"]), rounds)
        else:
            logger.info("向量检索无命中: user=%s query=%s", user_id, user_msg[:50])
    except Exception as e:
        logger.error("向量检索失败(已降级): %s", e)

    return state


def generate_node(state: AgentState, emotion_svc: EmotionService) -> AgentState:
    """回复生成节点：组装 system prompt + user message，调用 LLM 生成回复。

    完成后发射 'chat.completed' 事件，携带完整对话上下文。
    """
    if settings.TEST_MODE:
        state["final_response"] = "（测试模式）这是假回复，用于高并发压测。"
        state["need_regenerate"] = False
        return state

    if state.get("final_response") and not state.get("need_regenerate"):
        return state

    role_type = state.get("role_type", "温柔贤淑型")
    emotion = state.get("emotion", {"label": "neutral", "score": 0.5})
    memory_text = state.get("memory_text", "")
    user_input = state["user_input"]
    aff_info = state.get("aff_info", "亲密度10, 信任10")
    unlock_info = state.get("unlock_info", "")
    style = EmotionService.get_emotion_style(emotion["label"], emotion["score"])

    system_prompt = PromptFactory.system_prompt(role_type, style, memory_text, aff_info, unlock_info)

    if state.get("need_regenerate") and state.get("regenerate_context"):
        ctx = state["regenerate_context"]
        human_content = PromptFactory.regenerate(ctx["user_msg"], ctx["ai_msg"])
    else:
        human_content = user_input

    messages = [SystemMessage(content=system_prompt), HumanMessage(content=human_content)]
    resp = _get_llm().invoke(messages)
    state["final_response"] = resp.content
    state["need_regenerate"] = False
    return state
