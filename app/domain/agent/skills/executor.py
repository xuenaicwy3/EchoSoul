"""
Skill 执行器 —— 管理 Skill 的触发、激活、执行、清理全生命周期。

在 Agent 的 router_node 之前调用，检查用户输入是否触发任何 Skill。
触发的 Skill 被激活后，其工具自动注册到 ToolRegistry，LLM 即可调用。
"""
import logging
from typing import List

from app.core.events import bus
from app.domain.agent.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


class SkillExecutor:
    """Skill 生命周期管理器。

    用法（在 router_node 调用前）:
      state = await executor.process_triggers(state, tool_registry)
    """

    def __init__(self, skill_registry: SkillRegistry) -> None:
        self._registry = skill_registry
        self._initialized = False

    def initialize(self) -> int:
        """启动时初始化 Skill 发现（Level 1）。"""
        count = self._registry.initialize()
        self._initialized = True
        logger.info("SkillExecutor: 初始化完成，发现 %d 个 Skill", count)
        return count

    async def process_triggers(self, state: dict, tool_registry) -> dict:
        """检查用户输入 → 激活匹配的 Skill → 注册工具。

        Args:
            state: AgentState 字典（langgraph 用 dict 传递）。
            tool_registry: ToolRegistry 实例。

        Returns:
            更新后的 state（设置 active_skill 字段）。
        """
        if not self._initialized:
            return state

        user_input = state.get("user_input", "")
        triggered: List[str] = self._registry.check_triggers(user_input)

        if not triggered:
            return state

        # 激活每个触发的 Skill
        active_list = []
        for name in triggered:
            ok = self._registry.activate_skill(name, tool_registry)
            if ok:
                active_list.append(name)

                # 发事件
                try:
                    await bus.emit("skill.activated", {
                        "skill_name": name,
                        "user_id": state.get("user_id", ""),
                    })
                except Exception:
                    pass

        if active_list:
            state["active_skill"] = ",".join(active_list)
            logger.info("SkillExecutor: 已激活 %s", active_list)

        return state

    async def cleanup_session(self, state: dict, tool_registry) -> dict:
        """会话结束时停用所有 Skill，清除工具注册。"""
        if state.get("active_skill"):
            self._registry.deactivate_all(tool_registry)
            state["active_skill"] = ""
            logger.info("SkillExecutor: 会话清理完成")
        return state

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def active_skills(self) -> List[str]:
        return self._registry.active_skills
