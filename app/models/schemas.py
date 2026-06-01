from langgraph._internal._typing import TypedDictLikeV1
from pydantic import BaseModel, Field
from typing import Literal, Dict, Any, Optional, List, TypedDict

class EmotionResult(BaseModel):
    """情绪分析的结构化输出"""
    label: Literal[
        "admiration", "amusement", "anger", "annoyance", "approval",
        "caring", "confusion", "curiosity", "desire", "disappointment",
        "disapproval", "disgust", "embarrassment", "excitement", "fear",
        "gratitude", "grief", "joy", "love", "nervousness",
        "optimism", "pride", "realization", "relief", "remorse",
        "sadness", "surprise", "neutral"
    ] = Field(description="最匹配的情绪标签")
    score: float = Field(ge=0.0, le=1.0, description="置信度分数，0到1之间")

class ChatRequest(BaseModel):
    user_id: str
    message: str
    role_type: Optional[str] = None  # 新增：前端传入的当前角色

class ChatResponse(BaseModel):
    reply: str
    emotion: Dict[str, Any]
    role: Optional[str] = None

class AffectionResponse(BaseModel):
    intimacy: float
    trust: float
    fun: float
    growth: float
    level: int
    unlocks: List[str]


class AgentState(TypedDict):
    """对话状态，LangGraph 使用 TypedDict 作为状态类型"""
    user_id: str
    user_input: str
    role_type: Optional[str]
    emotion: Dict[str, Any]
    memory_text: str
    final_response: Optional[str]
    need_regenerate: bool
    regenerate_context: Optional[Dict[str, str]]
    aff_info: str
    unlock_info: str
