"""
Harness 层 —— 单 Agent 编排器（字节 DeerFlow 同款架构）。

职责：
  1. 聚合 Context 层数据 → 构建 AgentState
  2. 管理 Harness 层组件（ToolRegistry、SkillRegistry、MCP）
  3. 编排 Agent 生命周期（invoke / stream / interrupt / resume）
  4. 对上层（FastAPI / Celery）暴露统一调用接口

Harness 三层协作流程:
  Context 层 ──(数据注入)──→ AgentHarness ──(调用)──→ Model 层
                   │
                   ├── ToolRegistry (10 内置工具)
                   ├── SkillRegistry (4 技能包)
                   ├── MCPClientManager (外部 MCP 工具)
                   └── EchoSoulAgent (LangGraph 状态图)
"""
import logging
from typing import Optional, Dict, Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.errors import GraphInterrupt

from app.core.config import get_settings
from app.harness.context import HarnessContext
from app.harness.model import ModelProvider, ModelConfig
from app.domain.emotion.service import EmotionService
from app.domain.agent.graph import EchoSoulAgent
from app.domain.agent.tools.registry import ToolRegistry
from app.domain.agent.tools.companion_tools import register_all_companion_tools
from app.domain.agent.skills.registry import SkillRegistry
from app.domain.agent.skills.executor import SkillExecutor

logger = logging.getLogger(__name__)

# 敏感工具白名单（Harness 层配置，改这里不动代码）
SENSITIVE_TOOLS = [
    "update_affection",
    "do_game_action",
    "set_role_style",
    "progress_story",
]


class AgentHarness:
    """Harness 层 —— 单 Agent 编排器。

    对应字节 DeerFlow 的 Gateway 角色（单 Agent 版本）。
    管理 Context → Harness → Model 三层的完整生命周期。

    用法:
      harness = AgentHarness()
      harness.setup()                                          # 启动时初始化
      result = harness.invoke(context)                         # 同步执行
      stream = harness.stream(context)                         # 流式执行
      harness.resume(resume_value, thread_id)                  # 从中断恢复
      harness.shutdown()                                       # 关闭时清理
    """

    def __init__(
        self,
        model_config: Optional[ModelConfig] = None,
        checkpointer: Optional[BaseCheckpointSaver] = None,
    ):
        self.settings = get_settings()

        # ---- Model 层 ----
        self.model_provider = ModelProvider(model_config)
        logger.info(
            "[Harness] Model 层: chat=%s emotion=%s",
            self.model_provider.config.chat_model,
            self.model_provider.config.emotion_model,
        )

        # ---- Harness 层组件 ----
        self.tool_registry = ToolRegistry()
        self.skill_registry: Optional[SkillRegistry] = None
        self.skill_executor: Optional[SkillExecutor] = None
        self.mcp_manager = None

        # Checkpointer
        self.checkpointer = checkpointer or MemorySaver()

        # ---- Agent ----
        self.emotion_svc = EmotionService()
        self.agent: Optional[EchoSoulAgent] = None

        self._setup_done = False

    # ==================== 生命周期 ====================

    def setup(self) -> "AgentHarness":
        """启动时初始化 Harness 层所有组件。

        1. 注册 10 个内置陪伴工具
        2. 发现并加载 Skills
        3. 连接 MCP 服务器
        4. 构建 LangGraph Agent
        """
        if self._setup_done:
            return self

        logger.info("[Harness] === SETUP START ===")

        # 1. 内置工具（Function Calling）
        register_all_companion_tools(self.tool_registry)
        logger.info("[Harness] FC 层: %d 个内置工具", self.tool_registry.tool_count)

        # 2. Skills 系统
        if self.settings.ENABLE_SKILLS:
            self.skill_registry = SkillRegistry(self.settings.SKILLS_DIR)
            self.skill_registry.initialize()
            self.skill_executor = SkillExecutor(self.skill_registry)
            self.skill_executor.initialize()
            logger.info("[Harness] Skills 层: %d 个技能包", self.skill_registry.skill_count)

        # 3. MCP 客户端
        if self.settings.ENABLE_MCP:
            from app.domain.agent.mcp.client import MCPClientManager
            from app.domain.agent.mcp.adapter import adapt_mcp_tools
            import asyncio

            self.mcp_manager = MCPClientManager(self.settings.MCP_CONFIG_PATH)
            loop = asyncio.new_event_loop()
            connected = loop.run_until_complete(self.mcp_manager.connect())
            loop.close()

            if connected:
                mcp_tools = self.mcp_manager.get_mcp_tools()
                adapters = adapt_mcp_tools(mcp_tools)
                for a in adapters:
                    self.tool_registry.register_mcp(a)
                logger.info("[Harness] MCP 层: %d 个外部工具", len(adapters))
            else:
                logger.info("[Harness] MCP 层: 未连接")

        # 4. 构建 Agent
        self.agent = EchoSoulAgent(
            emotion_svc=self.emotion_svc,
            checkpointer=self.checkpointer,
            tool_registry=self.tool_registry,
            skill_executor=self.skill_executor,
            mcp_manager=self.mcp_manager,
        )
        logger.info("[Harness] Agent 图: %d 节点", len(self.agent.graph.nodes))

        self._setup_done = True
        logger.info("[Harness] === SETUP DONE (tools=%d skills=%s mcp=%s) ===",
                    self.tool_registry.tool_count,
                    self.skill_registry.skill_count if self.skill_registry else 0,
                    "on" if self.mcp_manager and self.mcp_manager.is_connected else "off")
        return self

    def shutdown(self):
        """关闭 Harness，释放资源。"""
        if self.mcp_manager:
            import asyncio
            loop = asyncio.new_event_loop()
            loop.run_until_complete(self.mcp_manager.disconnect())
            loop.close()
        logger.info("[Harness] shutdown complete")

    # ==================== Context 注入 ====================

    def build_state(self, context: HarnessContext) -> dict:
        """Context 层 → AgentState 字典。

        Context 层数据通过此方法注入 Harness 层，Harness 不直接访问数据库。
        """
        return context.to_agent_state()

    # ==================== 执行接口 ====================

    def invoke(self, context: HarnessContext, thread_id: str = None) -> Dict[str, Any]:
        """同步执行 Agent（Celery 模式）。

        Args:
            context: Context 层数据（记忆/好感度/会话状态）。
            thread_id: 线程 ID（默认取 user_id）。

        Returns:
            {
                "reply": str,
                "emotion": dict,
                "tools": [...],
                "status": "complete" | "pending_approval",
                "interrupt": {...},   # 仅中断时
            }
        """
        if not self._setup_done:
            self.setup()

        state = self.build_state(context)
        thread_id = thread_id or context.session.user_id
        config = {"configurable": {"thread_id": thread_id}}

        try:
            result = self.agent.invoke(state, config)
            return {
                "reply": result.get("final_response", ""),
                "emotion": result.get("emotion", {}),
                "tools": result.get("tool_executions", []),
                "status": "complete",
            }
        except GraphInterrupt as e:
            interrupt_data = e.args[0] if e.args else {}
            logger.info("[Harness] INTERRUPT: %s", [t.get("name") for t in interrupt_data.get("sensitive_tools", [])])
            return {
                "reply": "",
                "emotion": {},
                "tools": [],
                "status": "pending_approval",
                "interrupt": interrupt_data,
                "thread_id": thread_id,
            }

    def stream(self, context: HarnessContext, thread_id: str = None):
        """同步流式执行 Agent。

        产出 LangGraph 状态快照。用于 Celery 或同步场景。
        """
        if not self._setup_done:
            self.setup()

        state = self.build_state(context)
        thread_id = thread_id or context.session.user_id
        config = {"configurable": {"thread_id": thread_id}}

        return self.agent.stream(state, config)

    async def astream(self, context: HarnessContext, thread_id: str = None):
        """异步流式执行 Agent（状态快照级别）。

        Yields:
            dict: 每个节点完成后的 LangGraph 状态快照。
        """
        import asyncio

        if not self._setup_done:
            self.setup()

        state = self.build_state(context)
        thread_id = thread_id or context.session.user_id
        config = {"configurable": {"thread_id": thread_id}}

        queue: asyncio.Queue = asyncio.Queue()

        def _run_in_thread():
            try:
                for chunk in self.agent.stream(state, config):
                    asyncio.run_coroutine_threadsafe(
                        queue.put(("chunk", chunk)),
                        asyncio.get_event_loop(),
                    )
                asyncio.run_coroutine_threadsafe(
                    queue.put(("done", None)),
                    asyncio.get_event_loop(),
                )
            except Exception as e:
                asyncio.run_coroutine_threadsafe(
                    queue.put(("error", e)),
                    asyncio.get_event_loop(),
                )

        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, _run_in_thread)

        while True:
            msg_type, payload = await queue.get()
            if msg_type == "chunk":
                yield payload
            elif msg_type == "done":
                break
            elif msg_type == "error":
                raise payload

    async def astream_events(self, context: HarnessContext, thread_id: str = None):
        """异步流式执行 Agent（逐 token 级别，含 LLM 流式输出）。

        使用 LangGraph graph.astream_events(version="v2") 捕获:
          - on_chat_model_stream: LLM 每生成一个 token
          - on_tool_start/end: 工具执行起止
          - on_chain_start/end: 节点进入/退出

        Yields:
            dict: {"event": "on_chat_model_stream", "data": {...}, "name": "router", ...}
        """
        if not self._setup_done:
            self.setup()

        state = self.build_state(context)
        thread_id = thread_id or context.session.user_id

        # SSE 路径用 InMemorySaver（支持 async aget_tuple）
        from langgraph.checkpoint.memory import InMemorySaver
        _workflow = self.agent._build_uncompiled()
        _compiled = _workflow.compile(checkpointer=InMemorySaver())

        config = {"configurable": {"thread_id": thread_id}}

        async for event in _compiled.astream_events(state, config, version="v2"):
            kind = event.get("event", "")
            if kind in (
                "on_chat_model_start",
                "on_chat_model_stream",
                "on_chat_model_end",
                "on_tool_start",
                "on_tool_end",
                "on_chain_start",
                "on_chain_end",
            ):
                yield {
                    "event": kind,
                    "name": event.get("name", ""),
                    "data": event.get("data", {}),
                    "metadata": event.get("metadata", {}),
                }

    def resume(self, resume_value: dict, thread_id: str):
        """从中断点恢复执行。

        Args:
            resume_value: {"approved": ["tool1"], "rejected": ["tool2"]}
            thread_id: 与中断时的 thread_id 一致
        """
        if not self._setup_done:
            self.setup()

        config = {"configurable": {"thread_id": thread_id}}
        return self.agent.resume(resume_value, config)

    def get_state(self, thread_id: str):
        """查询线程状态（是否在中断中）。"""
        if not self._setup_done:
            self.setup()

        config = {"configurable": {"thread_id": thread_id}}
        return self.agent.get_state(config)

    # ==================== 诊断 ====================

    def get_stats(self) -> dict:
        return {
            "model": self.model_provider.config.chat_model,
            "tools": self.tool_registry.get_stats(),
            "skills": self.skill_registry.skill_count if self.skill_registry else 0,
            "mcp_connected": self.mcp_manager.is_connected if self.mcp_manager else False,
            "sensitive_tools": SENSITIVE_TOOLS,
            "agent_nodes": len(self.agent.graph.nodes) if self.agent else 0,
        }
