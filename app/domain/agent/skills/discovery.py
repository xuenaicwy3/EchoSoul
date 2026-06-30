"""
Skill 发现器 —— 扫描 SKILLS_DIR 目录，解析 SKILL.md 文件。

SKILL.md 格式：
  ---
  name: skill-name
  version: 1.0.0
  description: 一句话描述
  trigger: 触发关键词（可选）
  ---
  ## Overview
  ...
  ## Capabilities
  - cap1
  - cap2
  ## Triggers
  - trigger1
  ## Tool Definitions
  ```json
  {...}
  ```
"""
import json
import logging
import re
from pathlib import Path
from typing import List, Optional

from app.domain.agent.skills.models import SkillMetadata, SkillBrief, SkillDefinition

logger = logging.getLogger(__name__)


class SkillDiscoverer:
    """扫描指定目录，解析 SKILL.md 文件为 SkillDefinition。"""

    def __init__(self, skills_dir: str) -> None:
        self._skills_dir = Path(skills_dir)

    def discover_all(self) -> List[SkillDefinition]:
        """扫描 skills 目录，返回所有 SkillDefinition。"""
        if not self._skills_dir.exists():
            logger.info("Skills 目录不存在: %s", self._skills_dir)
            return []

        skills: List[SkillDefinition] = []
        for item in sorted(self._skills_dir.iterdir()):
            if not item.is_dir():
                continue
            skill_md = item / "SKILL.md"
            if not skill_md.exists():
                continue

            try:
                skill = self._parse_skill_md(skill_md)
                if skill:
                    skills.append(skill)
                    logger.info("发现 Skill: %s v%s", skill.metadata.name, skill.metadata.version)
            except Exception as e:
                logger.error("Skill 解析失败: %s — %s", skill_md, e)

        logger.info("Skill 发现完成: 总共 %d 个", len(skills))
        return skills

    def _parse_skill_md(self, path: Path) -> Optional[SkillDefinition]:
        """解析单个 SKILL.md 文件。"""
        content = path.read_text(encoding="utf-8")

        # 1. 提取 YAML frontmatter（Level 1）
        frontmatter = self._parse_frontmatter(content)
        if not frontmatter:
            logger.warning("SKILL.md 缺少 frontmatter: %s", path)
            return None

        metadata = SkillMetadata(
            name=frontmatter.get("name", ""),
            version=frontmatter.get("version", "1.0.0"),
            description=frontmatter.get("description", ""),
            author=frontmatter.get("author", "EchoSoul"),
            trigger=frontmatter.get("trigger", ""),
        )

        if not metadata.name:
            logger.warning("SKILL.md 缺少 name: %s", path)
            return None

        # 2. 移除 frontmatter 后的 body
        body = re.sub(r"^---\n.*?\n---\n", "", content, flags=re.DOTALL).strip()

        # 3. 解析 Level 2 信息（Overview / Capabilities / Triggers）
        brief = self._parse_brief(body)

        # 4. 解析 Level 3 信息（Tool Definitions）
        tool_defs = self._parse_tool_definitions(body)

        return SkillDefinition(
            metadata=metadata,
            brief=brief,
            tool_definitions=tool_defs,
        )

    def _parse_frontmatter(self, content: str) -> dict:
        """解析 YAML frontmatter（简化版，不依赖 pyyaml）。"""
        match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        if not match:
            return {}

        frontmatter_text = match.group(1)
        result = {}
        for line in frontmatter_text.split("\n"):
            line = line.strip()
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                result[key] = value
        return result

    def _parse_brief(self, body: str) -> SkillBrief:
        """从 Markdown body 提取 Level 2 信息。"""
        # 提取 ## Overview 后面的段落
        overview = ""
        overview_match = re.search(r"##\s*Overview\s*\n(.*?)(?=\n##|\Z)", body, re.DOTALL)
        if overview_match:
            overview = overview_match.group(1).strip()

        # 提取 ## Capabilities 下的列表
        capabilities: List[str] = []
        cap_match = re.search(r"##\s*Capabilities\s*\n(.*?)(?=\n##|\Z)", body, re.DOTALL)
        if cap_match:
            for line in cap_match.group(1).strip().split("\n"):
                line = line.strip()
                if line.startswith("- "):
                    capabilities.append(line[2:])

        # 提取 ## Triggers 下的列表
        triggers: List[str] = []
        trig_match = re.search(r"##\s*Triggers\s*\n(.*?)(?=\n##|\Z)", body, re.DOTALL)
        if trig_match:
            for line in trig_match.group(1).strip().split("\n"):
                line = line.strip()
                if line.startswith("- "):
                    triggers.append(line[2:])

        return SkillBrief(
            overview=overview,
            capabilities=capabilities,
            triggers=triggers,
        )

    def _parse_tool_definitions(self, body: str) -> List[dict]:
        """从 Markdown body 提取 Level 3 工具定义。"""
        tools: List[dict] = []

        # 查找所有 JSON 代码块
        json_blocks = re.findall(r"```json\s*\n(.*?)\n```", body, re.DOTALL)
        for block in json_blocks:
            try:
                tool_def = json.loads(block)
                if isinstance(tool_def, dict) and "name" in tool_def:
                    tools.append(tool_def)
            except json.JSONDecodeError:
                logger.debug("JSON 解析失败，跳过: %.50s...", block)

        return tools
