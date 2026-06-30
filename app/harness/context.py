"""
Harness Context 层 —— 高频迭代，改数据不改代码。

职责：聚合所有运行时上下文数据，注入 Agent 执行流程。
变 Context 层不需要改 Harness 层代码。
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MemoryContext:
    """用户长期记忆上下文。

    由 VectorMemoryService 在 Agent 执行前填充。
    包含三层记忆：事实层 + 情感层 + 关系层。
    """
    structured_mem: str = ""       # Redis 缓存的结构化记忆
    chroma_mem: str = ""           # ChromaDB 语义记忆
    recent_facts: List[str] = field(default_factory=list)
    recent_emotions: List[Dict[str, Any]] = field(default_factory=list)
    milestones: List[str] = field(default_factory=list)

    @property
    def combined(self) -> str:
        """合并所有记忆文本，用于注入 system prompt。"""
        parts = []
        if self.chroma_mem:
            parts.append(self.chroma_mem)
        if self.structured_mem:
            parts.append(self.structured_mem)
        return "\n".join(parts)

    @property
    def is_empty(self) -> bool:
        return not self.chroma_mem and not self.structured_mem


@dataclass
class RelationshipContext:
    """用户与角色的关系状态。

    由 AffectionService 在 Agent 执行前填充。
    """
    intimacy: float = 10.0
    trust: float = 10.0
    fun: float = 10.0
    growth: float = 10.0
    level: int = 0
    style_modifier: str = ""
    story_unlocked: bool = False

    @property
    def aff_info(self) -> str:
        return f"亲密度{self.intimacy:.0f}, 信任{self.trust:.0f}, 趣味{self.fun:.0f}, 成长{self.growth:.0f}"

    @property
    def unlock_info(self) -> str:
        parts = []
        if self.level >= 1:
            parts.append("关系等级 Lv.%d" % self.level)
        if self.style_modifier:
            parts.append(self.style_modifier)
        if self.story_unlocked:
            parts.append("故事模式已解锁")
        return ", ".join(parts) if parts else ""


@dataclass
class SessionContext:
    """当前会话上下文。"""
    user_id: str = ""
    role_type: str = "温柔贤淑型"
    user_input: str = ""
    emotion: Dict[str, Any] = field(default_factory=lambda: {"label": "neutral", "score": 0.5})
    need_regenerate: bool = False
    regenerate_context: Optional[Dict[str, str]] = None
    active_skills: List[str] = field(default_factory=list)
    interaction_count: int = 0


@dataclass
class HarnessContext:
    """聚合全部 Context 层数据。

    此类是 Harness 层获取运行时数据的唯一入口。
    变 Context 数据 = 创建新的 HarnessContext 实例，不改任何 Harness 代码。
    """
    session: SessionContext = field(default_factory=SessionContext)
    memory: MemoryContext = field(default_factory=MemoryContext)
    relationship: RelationshipContext = field(default_factory=RelationshipContext)

    def to_agent_state(self) -> dict:
        """转换为 LangGraph AgentState 字典。"""
        return {
            "user_id": self.session.user_id,
            "user_input": self.session.user_input,
            "role_type": self.session.role_type,
            "emotion": self.session.emotion,
            "memory_text": self.memory.combined,
            "final_response": None,
            "need_regenerate": self.session.need_regenerate,
            "regenerate_context": self.session.regenerate_context,
            "aff_info": self.relationship.aff_info,
            "unlock_info": self.relationship.unlock_info,
            "tool_calls": [],
            "tool_messages": [],
            "tool_executions": [],
            "interaction_count": 0,
            "active_skill": ",".join(self.session.active_skills) if self.session.active_skills else "",
        }
