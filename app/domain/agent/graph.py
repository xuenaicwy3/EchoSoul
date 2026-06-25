"""
EchoSoulAgent —— 心流虚拟伴侣智能体。

封装 LangGraph 状态图的构建和执行，通过事件总线解耦副作用。
"""
import logging
from typing import Optional

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, END

from app.core.config import get_settings
from app.models.schemas import AgentState
from app.domain.agent.nodes import (
    select_role_node,
    emotion_node,
    memory_node,
    generate_node,
)
from app.domain.emotion.service import EmotionService

logger = logging.getLogger(__name__)


class EchoSoulAgent:
    """封装对话处理完整生命周期的智能体。"""

    def __init__(
        self,
        emotion_svc: EmotionService,
        checkpointer: Optional[BaseCheckpointSaver] = None,
    ):
        self.settings = get_settings()
        self.emotion_svc = emotion_svc
        self.checkpointer = checkpointer or MemorySaver()
        self.graph = self._build_graph()
        logger.info("EchoSoulAgent 初始化完成, model=%s", self.settings.LLM_MODEL)

    def _build_graph(self) -> StateGraph:
        """构建 LangGraph 状态图（4 个节点 + 线性边）。"""
        workflow = StateGraph(AgentState)
        workflow.add_node("select_role", lambda s: select_role_node(s, self.emotion_svc))
        workflow.add_node("emotion", lambda s: emotion_node(s, self.emotion_svc))
        workflow.add_node("memory", lambda s: memory_node(s, self.emotion_svc))
        workflow.add_node("generate", lambda s: generate_node(s, self.emotion_svc))

        workflow.set_entry_point("select_role")
        workflow.add_edge("select_role", "emotion")
        workflow.add_edge("emotion", "memory")
        workflow.add_edge("memory", "generate")
        workflow.add_edge("generate", END)

        compiled = workflow.compile(checkpointer=self.checkpointer)
        logger.info("LangGraph 状态图构建完成")
        return compiled

    # ---- 执行接口 ----

    def invoke(self, state: AgentState, config: dict = None) -> AgentState:
        """同步执行状态图。"""
        if config is None:
            config = {"configurable": {"thread_id": state.get("user_id", "default")}}
        return self.graph.invoke(state, config)

    async def ainvoke(self, state: AgentState, config: dict = None) -> AgentState:
        """异步执行状态图。"""
        if config is None:
            config = {"configurable": {"thread_id": state.get("user_id", "default")}}
        logger.info("Agent.ainvoke 开始, thread_id=%s", config["configurable"]["thread_id"])
        result = await self.graph.ainvoke(state, config)
        logger.info("Agent.ainvoke 结束, 回复长度=%d", len(result.get("final_response", "")))
        return result
