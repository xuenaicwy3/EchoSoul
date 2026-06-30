"""Skills 数据模型 —— 三级渐进式加载。"""
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field


class SkillMetadata(BaseModel):
    """Level 1: 始终加载的元数据（~100 tokens/skill）。"""
    name: str
    version: str = "1.0.0"
    description: str
    author: str = "EchoSoul"
    trigger: str = ""  # 触发关键词，逗号分隔


class SkillBrief(BaseModel):
    """Level 2: 触发匹配时加载的简要说明（<5000 tokens）。"""
    overview: str = ""
    capabilities: List[str] = Field(default_factory=list)
    triggers: List[str] = Field(default_factory=list)


class SkillDefinition(BaseModel):
    """Level 3: 完整 Skill 定义（激活时加载）。"""
    metadata: SkillMetadata
    brief: Optional[SkillBrief] = None
    tool_definitions: List[Dict[str, Any]] = Field(default_factory=list)
    implementation_path: Optional[str] = None
    examples: List[str] = Field(default_factory=list)
