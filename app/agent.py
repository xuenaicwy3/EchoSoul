# app/agent.py (高并发修复版)
import asyncio
import logging
from typing import Optional, Any

import psycopg
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres import PostgresSaver
from langchain_core.messages import HumanMessage, SystemMessage
from langchain.chat_models import init_chat_model
from app.chat_history import ChatHistoryManager
from app.config import Settings
from app.roles import RoleCatalog
from app.prompts import PromptFactory
from app.emotions import EmotionService
from app.memory import MemoryService
from app.affection import AffectionService
from app.models.schemas import AgentState
from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)


class EchoSoulAgent:
    """
    心流虚拟伴侣智能体
    封装了对话处理的完整生命周期
    """
    def __init__(
        self,
        settings: Settings,
        emotion_svc: EmotionService,
        memory_svc: MemoryService,                             # 必须传入真实 MemoryService
        affection_svc: Optional[AffectionService] = None,
        checkpointer: Optional[BaseCheckpointSaver] = None,
    ):
        self.chat_history: ChatHistoryManager = ChatHistoryManager()
        self.settings = settings

        # 主对话 LLM
        self.llm = init_chat_model(
            model=settings.LLM_MODEL,
            model_provider="openai",
            temperature=0.8,
            max_tokens=512,
            api_key=settings.DASHSCOPE_API_KEY,
            base_url=settings.DASHSCOPE_BASE_URL,
        )
        self.emotion_svc = emotion_svc
        self.affection_svc = affection_svc or AffectionService()
        self.memory_svc = memory_svc                              # 直接保存真实服务

        # 检查点
        self.checkpointer = checkpointer or MemorySaver()
        self.graph = self._build_graph()
        logger.info("EchoSoulAgent 初始化完成，对话模型=%s", settings.LLM_MODEL)

    async def init_checkpointer(self):
        """使用 psycopg 异步连接初始化 PostgresSaver"""
        dsn = self.settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
        if '?' in dsn:
            dsn = dsn.split('?')[0]
        self.conn = await psycopg.AsyncConnection.connect(dsn)
        self.checkpointer = PostgresSaver(self.conn)
        self.checkpointer.setup()
        self.graph = self._build_graph()
        logger.info("PostgresSaver 初始化完成，图已编译")

    async def close_checkpointer(self):
        if self.conn:
            await self.conn.close()
            logger.info("PostgresSaver 连接已关闭")

    def _build_graph(self):
        if self.checkpointer is None:
            raise RuntimeError("必须先调用 init_checkpointer() 后才能构建图")
        workflow = StateGraph(AgentState)
        workflow.add_node("select_role", self._select_role_node)
        workflow.add_node("emotion", self._emotion_node)
        workflow.add_node("memory", self._memory_node)
        workflow.add_node("generate", self._generate_node)

        workflow.set_entry_point("select_role")
        workflow.add_edge("select_role", "emotion")
        workflow.add_edge("emotion", "memory")
        workflow.add_edge("memory", "generate")
        workflow.add_edge("generate", END)

        compiled = workflow.compile(checkpointer=self.checkpointer)
        logger.info("LangGraph 状态图构建完成")
        return compiled

    def _select_role_node(self, state: AgentState) -> AgentState:
        user_msg = state.get("user_input", "")
        if user_msg.startswith("[ROLE_SELECT]"):
            logger.info("[select_role] 角色已由 HTTP 层预设，当前 role_type = %s", state.get("role_type"))
            return state
        if not state.get("role_type"):
            default = "温柔贤淑型"
            greeting = RoleCatalog.get_role(default).greeting
            logger.info("[select_role] 未检测到角色，使用默认: %s", default)
            state["role_type"] = default
            state["final_response"] = greeting
            return state
        return state

    def _emotion_node(self, state: AgentState) -> AgentState:
        user_msg = state.get("user_input", "")
        if not user_msg:
            emotion = {"label": "neutral", "score": 0.5}
        else:
            emotion = self.emotion_svc.analyze(user_msg)
        state["emotion"] = emotion
        return state

    def _memory_node(self, state: AgentState) -> AgentState:
        user_msg = state["user_input"]
        role_type = state.get("role_type", "温柔贤淑型")
        # retrieve 是同步方法，在 Celery 同步任务中直接调用
        mem_text = self.memory_svc.retrieve(
            user_id=state["user_id"],
            query=user_msg,
            role_type=role_type
        )
        state["memory_text"] = mem_text
        return state

    def _generate_node(self, state: AgentState) -> AgentState:
        if state.get("final_response") and not state.get("need_regenerate"):
            return state
        role_type = state.get("role_type", "温柔贤淑型")
        emotion = state.get("emotion", {"label": "neutral", "score": 0.5})
        memory_text = state.get("memory_text", "")
        user_id = state["user_id"]
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
        resp = self.llm.invoke(messages)
        final_text = resp.content
        state["final_response"] = final_text
        state["need_regenerate"] = False
        return state

    def invoke(self, state: AgentState, config: RunnableConfig = None) -> AgentState:
        if config is None:
            config = {"configurable": {"thread_id": state.get("user_id", "default")}}
        result = self.graph.invoke(state, config)
        return result

    async def finalize_conversation(self, user_id: str, role_type: str, user_message: str,
                                    ai_reply: str, emotion: dict):
        if user_message and not user_message.startswith("[ROLE_SELECT]"):
            await self.chat_history.add_message(
                user_id=user_id,
                role_type=role_type,
                sender="user",
                message=user_message)
        if ai_reply:
            await self.chat_history.add_message(
                user_id=user_id,
                role_type=role_type,
                sender="ai",
                message=ai_reply)

        delta = self.affection_svc.calculate_delta(user_message, ai_reply, emotion)
        await self.affection_svc.update(user_id, role_type, delta)

        # 记忆存储是同步方法，用线程池执行，避免阻塞事件循环
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            self.memory_svc.store,
            user_id, user_message, ai_reply, emotion, role_type
        )