"""
Harness 层 —— 多 Agent 编排器（字节 DeerFlow Manager-Worker 模式）。

当前为预留接口，当工具量超过 30+ 且跨不同领域时激活。

架构:
                    ┌─────────────────┐
                    │  Lead Agent      │  ← Manager: 对话路由 + 全局决策
                    │  (EchoSoulAgent) │
                    └───────┬─────────┘
                            │ 委托子任务
            ┌───────────────┼───────────────┐
            ▼               ▼               ▼
    ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
    │ Memory Agent │ │  Game Agent  │ │ Story Agent  │  ← Workers: 领域专家
    │ recall/save  │ │ task/skin    │ │ story/branch │
    └──────────────┘ └──────────────┘ └──────────────┘
            │               │               │
            └───────────────┼───────────────┘
                            ▼
                    ┌─────────────────┐
                    │  Message Bus    │  ← 子 Agent 结果汇总
                    └─────────────────┘

触发条件（什么情况下从单 Agent 升级到多 Agent）:
  1. 工具数 > 30，单一 system prompt 塞不下
  2. 工具跨完全不相关领域（音乐/绘画/小说/游戏）
  3. 每个领域需要独立的上下文和决策逻辑
  4. 子 Agent 需要独立沙箱执行

使用方式（未来激活时）:
  from app.harness.multi_agent import MultiAgentHarness

  harness = MultiAgentHarness()
  harness.register_sub_agent("memory", memory_agent)
  harness.register_sub_agent("game", game_agent)
  harness.register_sub_agent("story", story_agent)
  harness.setup()

  # Lead Agent 自动判断将任务路由到哪个子 Agent
  result = harness.invoke(context)
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from app.harness.agent import AgentHarness
from app.harness.context import HarnessContext


@dataclass
class SubAgentSpec:
    """子 Agent 规格定义。

    对应 DeerFlow 的 sub-agent 配置。
    """
    name: str                          # 唯一名称，如 "memory_agent"
    description: str                   # 描述，供 Lead Agent 决策路由
    domain: str                        # 领域: memory / game / story / music / art
    tools: List[str] = field(default_factory=list)  # 该子 Agent 管理的工具名
    model_override: Optional[str] = None  # 可选：使用不同于 Lead Agent 的模型


class MultiAgentHarness(AgentHarness):
    """多 Agent 编排器（DeerFlow Manager-Worker 模式）。

    继承 AgentHarness，在其基础上增加:
      - 子 Agent 注册/管理
      - Lead Agent 路由决策
      - 子 Agent 结果汇总

    当前状态: 接口预留，不实际拆分 Agent。
    当 EchoSoul 扩展到音乐/绘画/小说等新领域时激活。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sub_agents: Dict[str, SubAgentSpec] = {}
        self._lead_agent = None  # 未来的 Lead Agent（Manager 角色）
        logger = __import__("logging").getLogger(__name__)
        logger.info("[MultiAgent] 接口就绪，等待领域拆分后激活")

    # ---- 子 Agent 注册 ----

    def register_sub_agent(self, spec: SubAgentSpec) -> None:
        """注册一个子 Agent。

        Lead Agent 会根据 spec.description 和 spec.domain
        决定何时将用户请求路由到此子 Agent。
        """
        self._sub_agents[spec.name] = spec
        logger = __import__("logging").getLogger(__name__)
        logger.info(
            "[MultiAgent] 注册子 Agent: %s domain=%s tools=%s",
            spec.name, spec.domain, spec.tools,
        )

    def unregister_sub_agent(self, name: str) -> None:
        self._sub_agents.pop(name, None)

    # ---- 路由逻辑（预留） ----

    def _route_to_sub_agent(self, context: HarnessContext) -> Optional[str]:
        """Lead Agent 路由决策。

        分析用户输入 → 决定由哪个子 Agent 处理。
        当前返回 None（全部由 Lead Agent 自身处理）。

        未来实现:
          1. 基于 trigger 词匹配（类似 Skills）
          2. 基于 LLM 意图分类
          3. 基于工具需求分析
        """
        # 未来：检查 context.session.user_input 匹配哪个 domain
        return None

    # ---- 执行（预留） ----

    def invoke(self, context: HarnessContext, thread_id: str = None):
        """多 Agent 执行。

        当前降级为单 Agent 模式。
        未来流程:
          1. Lead Agent 分析用户意图
          2. _route_to_sub_agent() → 选择子 Agent
          3. 子 Agent 执行 → 结果返回 Lead Agent
          4. Lead Agent 汇总 → 生成最终回复
        """
        sub = self._route_to_sub_agent(context)
        if sub:
            pass  # 未来：委托给子 Agent
        return super().invoke(context, thread_id)

    # ---- 诊断 ----

    @property
    def sub_agent_count(self) -> int:
        return len(self._sub_agents)

    def get_architecture_diagram(self) -> str:
        """生成当前架构图（文本版）。"""
        lines = [
            "EchoSoul Multi-Agent Architecture (DeerFlow Pattern)",
            "=" * 50,
            "",
            "  [Lead Agent] EchoSoulAgent",
            "       |",
        ]
        for name, spec in self._sub_agents.items():
            lines.append(f"       ├── [{name}] domain={spec.domain} tools={spec.tools}")
        lines.append(f"       |")
        lines.append(f"  [Model] {self.model_provider.config.chat_model}")
        lines.append(f"  [Tools] {self.tool_registry.tool_count} total")
        return "\n".join(lines)
