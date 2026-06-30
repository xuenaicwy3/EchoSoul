"""
MCP 工具适配器 —— 将 langchain-mcp-adapters 工具转换为内部 BaseTool 格式。

每个适配后的工具可注册到 ToolRegistry，与内置工具/技能工具统一调用。
"""
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class MCPToolAdapter:
    """将 MCP 工具适配为内部工具格式。

    适配后的对象兼容 ToolRegistry 的 register_mcp() 接口：
      - to_openai_tool() → OpenAI function calling schema
      - execute(args, context) → MCP 工具异步调用
    """

    def __init__(self, mcp_tool, server_name: str):
        """
        Args:
            mcp_tool: langchain-mcp-adapters 返回的原始工具对象。
            server_name: MCP 服务器名称。
        """
        self._mcp_tool = mcp_tool
        self._server_name = server_name

        # 构建 ToolSpec 兼容的元数据
        from app.domain.agent.tools.base import ToolSpec

        self.spec = ToolSpec(
            name=mcp_tool.name if hasattr(mcp_tool, "name") else f"mcp_{server_name}_tool",
            description=mcp_tool.description if hasattr(mcp_tool, "description") else "",
            parameters=self._extract_schema(mcp_tool),
            category="mcp",
        )

    def _extract_schema(self, mcp_tool) -> Dict[str, Any]:
        """从 MCP 工具对象提取参数 JSON Schema。"""
        if hasattr(mcp_tool, "args_schema") and mcp_tool.args_schema:
            try:
                return mcp_tool.args_schema.schema() if callable(mcp_tool.args_schema.schema) \
                    else mcp_tool.args_schema
            except Exception:
                pass

        # 兜底：空 schema
        return {"type": "object", "properties": {}}

    def to_openai_tool(self) -> Dict[str, Any]:
        """转换为 OpenAI-compatible function calling schema。"""
        return {
            "type": "function",
            "function": {
                "name": self.spec.name,
                "description": self.spec.description,
                "parameters": self.spec.parameters,
            },
        }

    async def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
        """执行 MCP 工具调用。

        Args:
            args: LLM 传入的参数。
            context: 执行上下文（当前未直接使用，MCP 工具自己处理）。

        Returns:
            工具执行结果。
        """
        try:
            result = await self._mcp_tool.ainvoke(args)
            return result
        except Exception as e:
            logger.error("MCP 工具 '%s' 执行失败: %s", self.spec.name, e)
            raise


def adapt_mcp_tools(mcp_tools: Dict[str, list]) -> list:
    """批量转换 MCP 工具。

    Args:
        mcp_tools: {server_name: [tool, ...]} 字典。

    Returns:
        MCPToolAdapter 实例列表。
    """
    adapters = []
    for server_name, tools in mcp_tools.items():
        for tool in tools:
            try:
                adapters.append(MCPToolAdapter(tool, server_name))
            except Exception as e:
                logger.error("MCP 工具适配失败: server=%s tool=%s — %s",
                           server_name, getattr(tool, "name", "?"), e)
    logger.info("MCP 工具适配完成: %d 个", len(adapters))
    return adapters
