"""
统一工具注册中心。

聚合 internal / mcp / skill 三类工具，提供：
  - get_all_tools(): 获取 OpenAI-format 工具列表（用于 bind_tools）
  - execute(): 按名称查找并执行工具（统一入口）
  - register_*(): 三类工具的分渠道注册
"""
import logging
from typing import Any, Dict, List, Optional

from app.domain.agent.tools.base import BaseTool, ToolSpec
from app.models.schemas import ToolResultObject

logger = logging.getLogger(__name__)


class ToolRegistry:
    """中央工具注册中心，聚合三种来源的工具。"""

    def __init__(self) -> None:
        self._internal_tools: Dict[str, BaseTool] = {}
        self._mcp_tools: Dict[str, BaseTool] = {}
        self._skill_tools: Dict[str, BaseTool] = {}
        # 执行计数器（用于监控）
        self._execution_counts: Dict[str, int] = {}

    # ---- 注册接口 ----

    def register_internal(self, tool: BaseTool) -> None:
        """注册内置陪伴工具。"""
        name = tool.spec.name
        tool.spec.category = "internal"
        self._internal_tools[name] = tool
        logger.debug("ToolRegistry: 注册内置工具 '%s'", name)

    def register_mcp(self, tool: BaseTool) -> None:
        """注册 MCP 来源工具（来自 langchain-mcp-adapters）。"""
        name = tool.spec.name
        tool.spec.category = "mcp"
        self._mcp_tools[name] = tool
        logger.debug("ToolRegistry: 注册 MCP 工具 '%s'", name)

    def register_skill(self, tool: BaseTool, skill_name: str) -> None:
        """注册技能工具（来自 Skill 系统）。"""
        name = tool.spec.name
        tool.spec.category = "skill"
        tool.spec.skill_name = skill_name
        self._skill_tools[name] = tool
        logger.debug("ToolRegistry: 注册技能工具 '%s' (skill=%s)", name, skill_name)

    def unregister_skill(self, tool_name: str) -> None:
        """注销技能工具（Skill 停用时调用）。"""
        self._skill_tools.pop(tool_name, None)
        logger.debug("ToolRegistry: 注销技能工具 '%s'", tool_name)

    def unregister_skill_all(self, skill_name: str) -> None:
        """注销指定 Skill 下的所有工具。"""
        to_remove = [
            name for name, tool in self._skill_tools.items()
            if tool.spec.skill_name == skill_name
        ]
        for name in to_remove:
            self._skill_tools.pop(name, None)
        if to_remove:
            logger.debug("ToolRegistry: 注销 Skill '%s' 的 %d 个工具", skill_name, len(to_remove))

    def unregister_mcp_all(self) -> None:
        """注销所有 MCP 工具（MCP 断开时调用）。"""
        count = len(self._mcp_tools)
        self._mcp_tools.clear()
        logger.debug("ToolRegistry: 注销全部 %d 个 MCP 工具", count)

    # ---- 查询接口 ----

    def get_all_tools(self) -> List[Dict[str, Any]]:
        """获取所有工具（OpenAI function schema 列表），用于 LLM bind_tools()。

        工具合并规则：internal < skill < mcp
        同名工具在工具数量不爆炸时基本不冲突，若有冲突后者覆盖前者的 LLM 可见定义。
        """
        all_tools: Dict[str, BaseTool] = {}
        # 优先级: internal → skill → mcp（后者覆盖同名）
        all_tools.update(self._internal_tools)
        all_tools.update(self._skill_tools)
        all_tools.update(self._mcp_tools)
        return [t.to_openai_tool() for t in all_tools.values()]

    def get_essential_tools(self) -> List[Dict[str, Any]]:
        """获取核心陪伴工具（不含 MCP，用于语音模式等低延迟场景）。"""
        all_tools: Dict[str, BaseTool] = {}
        all_tools.update(self._internal_tools)
        all_tools.update(self._skill_tools)
        return [t.to_openai_tool() for t in all_tools.values()]

    def get_tool_names(self) -> List[str]:
        """获取所有已注册工具名称列表。"""
        all_names = (
            list(self._internal_tools.keys())
            + list(self._skill_tools.keys())
            + list(self._mcp_tools.keys())
        )
        return all_names

    @property
    def tool_count(self) -> int:
        """已注册工具总数。"""
        return (
            len(self._internal_tools)
            + len(self._skill_tools)
            + len(self._mcp_tools)
        )

    # ---- 执行接口 ----

    async def execute(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Dict[str, Any],
    ) -> ToolResultObject:
        """按名称查找并执行工具（统一入口）。

        Args:
            tool_name: 工具名称。
            args: LLM 传入的参数。
            context: 执行上下文（user_id, role_type, service 引用等）。

        Returns:
            ToolResultObject: 统一执行结果。
        """
        # 注入 tool_call_id 到 args（由调用方设置）
        tool_call_id = args.pop("_tool_call_id", "")

        # 查找工具
        tool = (
            self._internal_tools.get(tool_name)
            or self._skill_tools.get(tool_name)
            or self._mcp_tools.get(tool_name)
        )

        if not tool:
            return ToolResultObject(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                result=None,
                success=False,
                error=f"Tool '{tool_name}' not found in registry",
                source="internal",
            )

        # 执行
        try:
            import time
            start = time.monotonic()
            result = await tool.execute(args, context)
            elapsed_ms = int((time.monotonic() - start) * 1000)

            # 更新计数器
            self._execution_counts[tool_name] = self._execution_counts.get(tool_name, 0) + 1

            logger.info(
                "ToolRegistry: '%s' 执行成功 (耗时=%dms)",
                tool_name, elapsed_ms,
            )
            return ToolResultObject(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                result=result,
                success=True,
                source=tool.spec.category,
            )
        except Exception as e:
            logger.error(
                "ToolRegistry: '%s' 执行失败: %s",
                tool_name, e, exc_info=True,
            )
            return ToolResultObject(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                result=None,
                success=False,
                error=str(e),
                source=tool.spec.category,
            )

    # ---- 诊断接口 ----

    def get_stats(self) -> Dict[str, Any]:
        """获取工具执行统计。"""
        return {
            "total_registered": self.tool_count,
            "internal": list(self._internal_tools.keys()),
            "mcp": list(self._mcp_tools.keys()),
            "skill": list(self._skill_tools.keys()),
            "execution_counts": dict(self._execution_counts),
        }
