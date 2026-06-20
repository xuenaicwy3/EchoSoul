from langgraph._internal._typing import TypedDictLikeV1
from pydantic import BaseModel, Field
from typing import Literal, Dict, Any, Optional, List, TypedDict

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
