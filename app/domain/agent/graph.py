"""
EchoSoulAgent —— 心流虚拟伴侣智能体（生产级 ReAct + Human-in-the-Loop）。

字节跳动级别 Agent 架构特征：
  1. 流式执行 (stream) — 不阻塞，中断时优雅暂停
  2. 中断/恢复 (interrupt/Command) — 敏感操作暂停等用户审批
  3. 动态路由 (Command.goto) — 节点根据状态自主决定下一跳
  4. 持久检查点 (PostgresSaver) — 中断状态跨重启存活
  5. 敏感工具白名单 — 写操作、角色切换等需人工确认

图结构:
  select_role → emotion → memory → router
                                      ├─ (no tool_calls) → generate → END
                                      └─ (has tool_calls) → interrupt_check
                                                              ├─ (need approval) → ⏸ INTERRUPT → tool_exec
                                                              └─ (safe tools) → tool_exec
                                                                                   └→ router (loop)
"""
import logging
from typing import Optional, List

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, END
from langgraph.types import Command

from app.core.config import get_settings
from app.models.schemas import AgentState
from app.domain.agent.nodes import (
    select_role_node,
    emotion_node,
    memory_node,
    router_node,
    interrupt_check_node,
    tool_exec_node,
    generate_node,
    _has_tool_calls,
    _needs_approval,
)
from app.domain.agent.tools.registry import ToolRegistry
from app.domain.agent.tools.companion_tools import register_all_companion_tools
from app.domain.emotion.service import EmotionService

logger = logging.getLogger(__name__)

# 需要人工审批的敏感工具（修改关系/游戏/角色/故事）
SENSITIVE_TOOLS: List[str] = [
    "update_affection",
    "do_game_action",
    "set_role_style",
    "progress_story",
]


class EchoSoulAgent:
    """生产级 ReAct Agent with Human-in-the-Loop。

    敏感工具（写操作/角色切换/游戏动作）在执行前会暂停等待用户审批。
    用户可 approve（批准执行）、reject（拒绝并附反馈）、edit（修改参数后执行）。

    执行模式：
      - invoke():  同步执行，遇中断抛 GraphInterrupt（Celery 模式）
      - stream():  流式执行，遇中断优雅暂停（FastAPI SSE 模式）
      - resume():  从中断点恢复执行
    """

    def __init__(
        self,
        emotion_svc: EmotionService,
        checkpointer: Optional[BaseCheckpointSaver] = None,
        tool_registry: Optional[ToolRegistry] = None,
        skill_executor=None,
        mcp_manager=None,
    ):
        self.settings = get_settings()
        self.emotion_svc = emotion_svc

        # 工具注册中心
        self.tool_registry = tool_registry or ToolRegistry()
        if not self.tool_registry._internal_tools:
            register_all_companion_tools(self.tool_registry)
            logger.info("已注册 %d 个内置陪伴工具", self.tool_registry.tool_count)

        # Skills / MCP
        self.skill_executor = skill_executor
        self.mcp_manager = mcp_manager

        # 检查点（生产环境用 PostgresSaver，开发用 MemorySaver）
        self.checkpointer = checkpointer or MemorySaver()

        # 构建图
        self.graph = self._build_graph()
        logger.info(
            "EchoSoulAgent(ReAct+HITL) 初始化: model=%s tools=%d skills=%s mcp=%s sensitive=%s",
            self.settings.LLM_MODEL,
            self.tool_registry.tool_count,
            "on" if skill_executor else "off",
            "on" if mcp_manager else "off",
            ",".join(SENSITIVE_TOOLS),
        )

    def _build_graph(self):
        """构建带中断审批的 ReAct StateGraph。

        节点拓扑:
          select_role → emotion → memory → router
                                            ├─ (无 tool_calls) → generate → END
                                            └─ (有 tool_calls) → interrupt_check
                                                                    ├─ (需审批) → ⏸ → tool_exec
                                                                    └─ (安全) → tool_exec
                                            tool_exec → router (循环)

        interrupt_check 节点行为：
          - 扫描 tool_calls 中的敏感工具
          - 有敏感工具 → interrupt() 暂停，返回审批信息给前端
          - 用户审批后 → Command(resume={"approved": [...], "rejected": [...]})
          - 全部安全 → 直接放行到 tool_exec
        """
        workflow = StateGraph(AgentState)

        # ---- Prefix 阶段 ----
        workflow.add_node("select_role", lambda s: select_role_node(s, self.emotion_svc))
        workflow.add_node("emotion", lambda s: emotion_node(s, self.emotion_svc))
        workflow.add_node("memory", lambda s: memory_node(s, self.emotion_svc))

        # ---- ReAct 阶段 ----
        workflow.add_node(
            "router",
            lambda s: router_node(s, self.emotion_svc, self.tool_registry),
        )
        workflow.add_node(
            "interrupt_check",
            lambda s: interrupt_check_node(s, SENSITIVE_TOOLS),
        )
        workflow.add_node(
            "tool_exec",
            lambda s: tool_exec_node(s, self.tool_registry),
        )
        workflow.add_node(
            "generate",
            lambda s: generate_node(s, self.emotion_svc),
        )

        # ---- 边 ----
        # emotion 和 memory 互不依赖，并行执行（Annotated reducer 处理状态合并）
        workflow.set_entry_point("select_role")
        workflow.add_edge("select_role", "emotion")
        workflow.add_edge("select_role", "memory")
        workflow.add_edge("emotion", "router")
        workflow.add_edge("memory", "router")
        workflow.add_conditional_edges("router", _has_tool_calls, {True: "interrupt_check", False: "generate"})
        workflow.add_conditional_edges("interrupt_check", _needs_approval, {True: "tool_exec", False: "generate"})
        workflow.add_edge("tool_exec", "router")
        workflow.add_edge("generate", END)

        compiled = workflow.compile(checkpointer=self.checkpointer)
        logger.info("LangGraph ReAct+HITL 状态图构建完成 (7节点)")
        return compiled

    def _build_uncompiled(self):
        """返回未编译的 StateGraph（SSE astream_events 用 InMemorySaver 编译）。"""
        workflow = StateGraph(AgentState)
        workflow.add_node("select_role", lambda s: select_role_node(s, self.emotion_svc))
        workflow.add_node("emotion", lambda s: emotion_node(s, self.emotion_svc))
        workflow.add_node("memory", lambda s: memory_node(s, self.emotion_svc))
        workflow.add_node("router", lambda s: router_node(s, self.emotion_svc, self.tool_registry))
        workflow.add_node("interrupt_check", lambda s: interrupt_check_node(s, SENSITIVE_TOOLS))
        workflow.add_node("tool_exec", lambda s: tool_exec_node(s, self.tool_registry))
        workflow.add_node("generate", lambda s: generate_node(s, self.emotion_svc))
        workflow.set_entry_point("select_role")
        workflow.add_edge("select_role", "emotion")
        workflow.add_edge("select_role", "memory")
        workflow.add_edge("emotion", "router")
        workflow.add_edge("memory", "router")
        workflow.add_conditional_edges("router", _has_tool_calls, {True: "interrupt_check", False: "generate"})
        workflow.add_conditional_edges("interrupt_check", _needs_approval, {True: "tool_exec", False: "generate"})
        workflow.add_edge("tool_exec", "router")
        workflow.add_edge("generate", END)
        return workflow

    # ==================== 执行接口 ====================

    def invoke(self, state: AgentState, config: dict = None) -> AgentState:
        """同步执行（Celery 模式）。

        遇 interrupt 会抛 GraphInterrupt，调用方需捕获并处理。
        """
        if config is None:
            config = {"configurable": {"thread_id": state.get("user_id", "default")}}
        return self.graph.invoke(state, config)

    async def ainvoke(self, state: AgentState, config: dict = None) -> AgentState:
        """异步执行（FastAPI 模式）。"""
        if config is None:
            config = {"configurable": {"thread_id": state.get("user_id", "default")}}
        logger.info(
            "Agent.ainvoke: thread=%s tools=%d",
            config["configurable"]["thread_id"],
            self.tool_registry.tool_count,
        )
        result = await self.graph.ainvoke(state, config)
        logger.info(
            "Agent.ainvoke 完成: reply_len=%d",
            len(result.get("final_response", "")),
        )
        return result

    def stream(self, state: AgentState, config: dict = None):
        """流式执行（FastAPI SSE 模式）。

        产出状态快照。遇 interrupt 时产出包含 __interrupt__ 的 chunk。
        调用方需迭代生成器，检测中断并展示审批 UI。
        """
        if config is None:
            config = {"configurable": {"thread_id": state.get("user_id", "default")}}
        logger.info("Agent.stream 开始: thread=%s", config["configurable"]["thread_id"])
        return self.graph.stream(state, config, stream_mode="values")

    def resume(self, resume_value: dict, config: dict):
        """从中断点恢复执行。

        Args:
            resume_value: 用户审批结果，如 {"approved": ["save_memory"], "rejected": ["update_affection"]}
            config: 线程配置（thread_id 必须与中断时一致）
        """
        logger.info("Agent.resume: thread=%s", config["configurable"]["thread_id"])
        return self.graph.stream(Command(resume=resume_value), config, stream_mode="values")

    def get_state(self, config: dict):
        """获取当前线程状态（用于检查是否在中断中）。"""
        return self.graph.get_state(config)

    # ==================== 诊断接口 ====================

    def get_stats(self) -> dict:
        return {
            "model": self.settings.LLM_MODEL,
            "tools": self.tool_registry.get_stats(),
            "sensitive_tools": SENSITIVE_TOOLS,
            "skills_enabled": self.skill_executor is not None,
            "mcp_enabled": self.mcp_manager is not None,
        }
