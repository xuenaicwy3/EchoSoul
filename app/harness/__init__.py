"""
EchoSoul Harness 架构 —— 字节跳动 DeerFlow 同款三层 Agent 基础设施。

三层分离：
  Context 层（高频变 — 改数据）: 记忆上下文、好感度状态、会话历史
  Harness 层（中频变 — 改配置）: 工具注册、技能发现、Agent 图编排、中断规则
  Model 层 （低频变 — 改 API）: LLM 模型选择、参数配置

单 Agent 入口：
  from app.harness import AgentHarness
  harness = AgentHarness(context, model_cfg)
  result = harness.invoke(state)

多 Agent 扩展（预留）：
  from app.harness import MultiAgentHarness
  harness = MultiAgentHarness(context, model_cfg)
  harness.register_sub_agent("memory_agent", ...)
"""
from app.harness.agent import AgentHarness

__all__ = ["AgentHarness"]
