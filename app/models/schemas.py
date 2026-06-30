from langgraph._internal._typing import TypedDictLikeV1
from pydantic import BaseModel, Field
from typing import Annotated, Literal, Dict, Any, Optional, List, TypedDict

from typing_extensions import NotRequired


# LangGraph 官方并行节点 reducer：取最新值
def _keep_latest(prev, new):
    return new


class EmotionResult(BaseModel):
    """情绪分析的结构化输出，标签需与 prompts.emotion_analysis_system 保持同步"""
    label: Literal[
        "joy", "sadness", "anger", "fear", "surprise",
        "love", "gratitude", "loneliness", "anxiety", "boredom",
        "disappointment", "hope", "envy", "guilt", "confusion",
        "sarcasm","mockery", "despair", "neutral"
    ] = Field(description="最匹配的情绪标签")
    score: float = Field(ge=0.0, le=1.0, description="置信度分数，0到1之间")


class ChatRequest(BaseModel):
    message: str
    role_type: Optional[str] = None
    enable_tools: bool = False  # 是否启用工具调用


class ChatResponse(BaseModel):
    reply: str
    emotion: Dict[str, Any]
    role: Optional[str] = None
    tools: Optional[List[Dict[str, Any]]] = None  # 工具执行摘要


class AffectionResponse(BaseModel):
    intimacy: float
    trust: float
    fun: float
    growth: float
    level: int
    unlocks: List[str]


# ==================== 工具调用数据结构 ====================


class ToolCallObject(BaseModel):
    """Provider-agnostic internal tool call representation."""
    tool_name: str
    tool_args: Dict[str, Any]
    tool_call_id: str
    source: Literal["internal", "mcp", "skill"]
    skill_name: Optional[str] = None


class ToolResultObject(BaseModel):
    """Unified tool execution result."""
    tool_call_id: str
    tool_name: str
    result: Any
    success: bool
    error: Optional[str] = None
    source: Literal["internal", "mcp", "skill"]


class ToolExecutionRecord(BaseModel):
    """工具执行记录，用于可观测性和前端展示。"""
    tool_name: str
    success: bool
    result_preview: Optional[str] = None  # 结果摘要（≤200 字符）
    error: Optional[str] = None
    duration_ms: int = 0


# ==================== Agent 状态 ====================


class AgentState(TypedDict):
    """对话状态，使用 Annotated + reducer 支持并行节点写入。"""
    user_id: Annotated[str, _keep_latest]
    user_input: Annotated[str, _keep_latest]
    role_type: Annotated[Optional[str], _keep_latest]
    emotion: Annotated[Dict[str, Any], _keep_latest]
    memory_text: Annotated[str, _keep_latest]
    final_response: Annotated[Optional[str], _keep_latest]
    need_regenerate: Annotated[bool, _keep_latest]
    regenerate_context: Annotated[Optional[Dict[str, str]], _keep_latest]
    aff_info: Annotated[str, _keep_latest]
    unlock_info: Annotated[str, _keep_latest]
    # ---- 工具调用字段 ----
    tool_calls: NotRequired[Annotated[List[Dict[str, Any]], _keep_latest]]
    tool_messages: NotRequired[Annotated[List[Dict[str, Any]], _keep_latest]]
    tool_executions: NotRequired[Annotated[List[Dict[str, Any]], _keep_latest]]
    interaction_count: NotRequired[Annotated[int, _keep_latest]]
    active_skill: NotRequired[Annotated[str, _keep_latest]]
