"""
Agent Skills 系统 —— 基于 Anthropic Agent Skills 开放标准的渐进式技能加载。

三级加载：
  Level 1 (启动时):     YAML frontmatter 元数据（name/description/trigger）~100 tokens/skill
  Level 2 (触发匹配时): SKILL.md body（Overview/Capabilities/Triggers）<5000 tokens
  Level 3 (显式激活时): Tool Definitions + Implementation + Examples

所有 Skill 位于 SKILLS_DIR 目录，每个 Skill 一个子目录，内含 SKILL.md。
"""
