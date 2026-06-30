"""
Agent 工具层 —— Function Calling + Skills + MCP 的统一工具注册与执行。

三层工具来源：
  - internal: 内置陪伴工具（companion_tools.py）
  - skill:    技能系统按需加载的工具
  - mcp:      MCP 服务器通过 langchain-mcp-adapters 接入的工具

所有工具通过 ToolRegistry 统一管理，对 LLM 暴露为 OpenAI-compatible function schema。
"""

from app.domain.agent.tools.base import BaseTool, ToolSpec
from app.domain.agent.tools.registry import ToolRegistry

__all__ = ["BaseTool", "ToolSpec", "ToolRegistry"]
