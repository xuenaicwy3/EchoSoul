"""
工具抽象基类。

所有工具（internal/skill/mcp）均继承 BaseTool，
ToolSpec 定义工具的 LLM-visible 元数据（name / description / JSON Schema 参数）。
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class ToolSpec(BaseModel):
    """工具元数据 —— 驱动 LLM function calling 的 schema 定义。

    字段与 OpenAI function calling 1:1 对应：
      - name:        函数名（LLM 决策 key）
      - description: 函数描述（LLM 何时调用此工具）
      - parameters:  JSON Schema（函数参数约束）
      - category:    "internal" | "mcp" | "skill"
    """
    name: str
    description: str
    parameters: Dict[str, Any]
    category: str = "internal"
    skill_name: Optional[str] = None


class BaseTool(ABC):
    """工具抽象基类。

    子类必须：
      1. 定义 spec 类属性（ToolSpec）
      2. 实现 execute(args, context) → Any

    context 字典包含执行上下文（user_id, role_type, emotion, 各类 service 引用等）。
    """

    spec: ToolSpec

    def to_openai_tool(self) -> Dict[str, Any]:
        """将工具定义转换为 OpenAI-compatible function calling schema。

        Returns:
            {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}
        """
        return {
            "type": "function",
            "function": {
                "name": self.spec.name,
                "description": self.spec.description,
                "parameters": self.spec.parameters,
            },
        }

    @abstractmethod
    async def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> Any:
        """执行工具逻辑。

        Args:
            args: LLM 传入的函数参数（已按 parameters JSON Schema 校验）。
            context: 执行上下文，包含 user_id / role_type / service 引用等。

        Returns:
            工具执行结果（将序列化为 ToolMessage content）。
        """
        ...
