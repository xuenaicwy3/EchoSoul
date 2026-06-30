"""
Skill 注册中心 —— 管理 Skill 的完整生命周期。

三级渐进式加载:
  Level 1 (initialize):     加载所有 Skill 的 YAML metadata
  Level 2 (check_triggers): 检查用户输入是否命中 Skill 触发器
  Level 3 (activate_skill): 加载完整 Skill（工具定义 + 示例），注册工具到 ToolRegistry
"""
import asyncio
import logging
from typing import Dict, List, Optional

from app.domain.agent.skills.models import SkillMetadata, SkillDefinition
from app.domain.agent.skills.discovery import SkillDiscoverer

logger = logging.getLogger(__name__)


class SkillRegistry:
    """Skill 注册中心。

    用法:
      registry = SkillRegistry("./skills")
      registry.initialize()                          # Level 1
      triggered = registry.check_triggers(user_msg)   # Level 2
      for name in triggered:
          registry.activate_skill(name, tool_registry) # Level 3
    """

    def __init__(self, skills_dir: str):
        self._discoverer = SkillDiscoverer(skills_dir)
        # 所有已发现的 Skill（全量定义）
        self._skills: Dict[str, SkillDefinition] = {}
        # Level 1 元数据（始终在内存中）
        self._metadata: Dict[str, SkillMetadata] = {}
        # Level 3 已激活的 Skill
        self._active: Dict[str, SkillDefinition] = {}

    # ---- Level 1: 初始化 ----

    def initialize(self) -> int:
        """扫描并加载所有 Skill 的元数据（Level 1）。

        Returns:
            发现的 Skill 数量。
        """
        skills = self._discoverer.discover_all()
        for skill in skills:
            self._skills[skill.metadata.name] = skill
            self._metadata[skill.metadata.name] = skill.metadata
        logger.info(
            "SkillRegistry: Level 1 完成，已加载 %d 个 Skill: %s",
            len(self._skills),
            list(self._skills.keys()),
        )
        return len(self._skills)

    # ---- Level 2: 触发器匹配 ----

    def check_triggers(self, user_input: str) -> List[str]:
        """检查用户输入是否命中 Skill 触发器。

        Args:
            user_input: 用户消息文本。

        Returns:
            匹配到的 Skill name 列表。
        """
        if not user_input:
            return []

        user_lower = user_input.lower()
        triggered: List[str] = []

        for name, skill in self._skills.items():
            if name in self._active:
                continue  # 已激活则跳过

            # 检查 frontmatter trigger 字段
            trigger_str = skill.metadata.trigger.lower()
            if trigger_str:
                keywords = [kw.strip() for kw in trigger_str.split(",")]
                if any(kw in user_lower for kw in keywords):
                    triggered.append(name)
                    continue

            # 检查 ## Triggers 中的列表
            if skill.brief:
                for trig in skill.brief.triggers:
                    if trig.lower() in user_lower:
                        triggered.append(name)
                        break

        if triggered:
            logger.info("Skill 触发匹配: %s ← '%s'", triggered, user_input[:50])
        return triggered

    # ---- Level 3: 激活/停用 ----

    def activate_skill(self, name: str, tool_registry) -> bool:
        """激活 Skill（Level 3），将其工具注册到 ToolRegistry。

        Args:
            name: Skill 名称。
            tool_registry: ToolRegistry 实例。

        Returns:
            True 若成功激活并注册工具。
        """
        skill = self._skills.get(name)
        if not skill:
            logger.warning("Skill '%s' 不存在，无法激活", name)
            return False

        if name in self._active:
            logger.debug("Skill '%s' 已激活，跳过", name)
            return True

        self._active[name] = skill

        # 注册 Skill 的工具
        if skill.tool_definitions:
            for td in skill.tool_definitions:
                from app.domain.agent.tools.base import BaseTool, ToolSpec

                spec = ToolSpec(
                    name=td.get("name", f"{name}_tool"),
                    description=td.get("description", ""),
                    parameters=td.get("parameters", {"type": "object", "properties": {}}),
                    category="skill",
                    skill_name=name,
                )

                # 创建动态工具（执行时通过 context 中的 handler 回调）
                tool = _DynamicSkillTool(spec, name)
                tool_registry.register_skill(tool, skill_name=name)

        logger.info(
            "Skill '%s' 已激活，注册 %d 个工具",
            name, len(skill.tool_definitions),
        )
        return True

    def deactivate_skill(self, name: str, tool_registry) -> bool:
        """停用 Skill，从 ToolRegistry 移除其工具。

        Args:
            name: Skill 名称。
            tool_registry: ToolRegistry 实例。
        """
        if name not in self._active:
            return False

        self._active.pop(name, None)
        tool_registry.unregister_skill_all(name)
        logger.info("Skill '%s' 已停用", name)
        return True

    def deactivate_all(self, tool_registry) -> None:
        """停用所有已激活的 Skill。"""
        for name in list(self._active.keys()):
            self.deactivate_skill(name, tool_registry)

    # ---- 查询 ----

    @property
    def active_skills(self) -> List[str]:
        return list(self._active.keys())

    @property
    def skill_count(self) -> int:
        return len(self._skills)

    @property
    def active_count(self) -> int:
        return len(self._active)

    def get_metadata_list(self) -> List[SkillMetadata]:
        """获取所有 Skill 的 Level 1 元数据（用于展示可用 Skill 列表）。"""
        return list(self._metadata.values())

    def get_active_trigger_hints(self) -> str:
        """获取已激活 Skill 的触发器提示文本（注入 system prompt）。"""
        if not self._active:
            return ""
        hints = []
        for name, skill in self._active.items():
            if skill.brief and skill.brief.triggers:
                hints.append(f"- {name}: {', '.join(skill.brief.triggers)}")
        if hints:
            return "当前可用技能:\n" + "\n".join(hints)
        return ""


# ==================== 动态工具 ====================


class _DynamicSkillTool:
    """从 SKILL.md 工具定义动态创建的工具适配器。

    工具的实际执行逻辑通过 context["skill_handlers"][skill_name][tool_name] 回调。
    """

    def __init__(self, spec, skill_name: str):
        from app.domain.agent.tools.base import ToolSpec as _ToolSpec
        self.spec: _ToolSpec = spec
        self._skill_name = skill_name

    def to_openai_tool(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.spec.name,
                "description": self.spec.description,
                "parameters": self.spec.parameters,
            },
        }

    async def execute(self, args: dict, context: dict) -> str:
        """执行 Skill 工具 —— 通过 context 中的 handler 回调。"""
        skill_handlers = context.get("skill_handlers", {})
        handler = skill_handlers.get(self._skill_name, {}).get(self.spec.name)

        if handler:
            result = handler(args, context)
            if asyncio.iscoroutine(result):
                result = await result
            return str(result) if result else ""

        # 无 handler 时的兜底
        return f"[{self.spec.name}] 工具已注册但无执行回调。参数: {args}"
