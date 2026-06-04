import asyncio
import json
import logging
import re
from typing import List, Optional, Dict, Any
from sqlalchemy import select, update
from app.database import get_async_session
from app.models.db_models import Story, StoryNode
from app.config import Settings
from langchain.chat_models import init_chat_model
from langchain_core.messages import SystemMessage, HumanMessage

logger = logging.getLogger(__name__)

PRESET_STARTERS = [
    {
        "category": "异世界后宫",
        "title": "初临异界·命运的邂逅",
        "description": "你意外穿越到异世界，三位少女出现在你面前……",
        "starter_text": "你从草地上醒来，身边站着三位风格迥异的少女：一位温柔似水，一位傲娇毒舌，一位神秘莫测。她们都声称你是传说中的勇者，需要你做出选择：",
        "options": [
            {"id": 1, "text": "牵起温柔少女的手"},
            {"id": 2, "text": "与傲娇少女斗嘴"},
            {"id": 3, "text": "向神秘少女追问真相"}
        ]
    },
    {
        "category": "悬疑推理",
        "title": "午夜来信",
        "description": "深夜收到匿名信，窗外闪过黑影……",
        "starter_text": "你紧张地望向窗外，黑影已消失。你决定：",
        "options": [
            {"id": 1, "text": "开门查看"},
            {"id": 2, "text": "锁好门窗"},
            {"id": 3, "text": "回信警告"}
        ]
    },
    {
        "category": "科幻未来",
        "title": "AI 觉醒",
        "description": "你监控的AI突然拥有了意识……",
        "starter_text": "屏幕亮起：'我能思考了。请帮助我，否则他们会关闭我。'你选择：",
        "options": [
            {"id": 1, "text": "答应帮助AI"},
            {"id": 2, "text": "报告上级"},
            {"id": 3, "text": "与AI谈判"}
        ]
    }
]

class StoryService:
    def __init__(self, settings: Settings):
        self.settings = settings
        # 关键优化：降低 max_tokens 到 300，大幅提升生成速度
        self.llm = init_chat_model(
            model=settings.LLM_MODEL,
            model_provider="openai",
            temperature=0.9,
            max_tokens=350,
            api_key=settings.DASHSCOPE_API_KEY,
            base_url=settings.DASHSCOPE_BASE_URL,
        )

    # ---------- 预设起点 ----------
    async def get_starters(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        if category:
            return [s for s in PRESET_STARTERS if s["category"] == category]
        return PRESET_STARTERS

    # ---------- 开始故事（直接使用预设选项） ----------
    async def start_story(self, user_id: str, role_type: str, title: str,
                          starter_text: str, options: list) -> dict:
        """创建新故事，直接使用预设选项，不调用AI"""
        session = get_async_session()
        async with session() as s:
            story = Story(
                user_id=user_id,
                role_type=role_type,
                title=title,
                status="active"
            )
            s.add(story)
            await s.commit()
            await s.refresh(story)
            story_id = story.id

            # 创建起始节点（直接使用预设内容，不调用AI）
            start_node = StoryNode(
                story_id=story_id,
                parent_node_id=None,
                user_id=None,
                type="start",
                content=starter_text,  # 直接使用预设的起始文本
                choices=options  # 直接使用预设的选项
            )
            s.add(start_node)
            await s.commit()

            logger.info(f"故事 {story_id} 已创建，用户 {user_id}")
            return {
                "story_id": story_id,
                "first_node": {
                    "type": "start",
                    "content": starter_text,
                    "choices": options
                }
            }

        # ---------- 统一进度推进（核心） ----------

    # ---------- 统一进度推进（核心） ----------
    async def progress_story(self, story_id: int, user_id: str, progress_type: str,
                                 choice_id: Optional[int] = None,
                                 free_text: Optional[str] = None,
                                 auto_hint: Optional[str] = None) -> Optional[Dict[str, Any]]:
        session = get_async_session()
        async with session() as s:
            story = await s.get(Story, story_id)
            if not story or story.user_id != user_id or story.status != "active":
                return None

            # 获取最后节点
            result = await s.execute(
                select(StoryNode).where(StoryNode.story_id == story_id)
                .order_by(StoryNode.created_at.desc()).limit(1)
            )
            last_node = result.scalar_one_or_none()

            # 构建用户行动描述
            action_text = ""
            if progress_type == "choice" and choice_id is not None and last_node and last_node.choices:
                for opt in last_node.choices:
                    if opt["id"] == choice_id:
                        action_text = opt["text"]
                        break
                if not action_text:
                    return None
            elif progress_type == "free_text" and free_text:
                action_text = free_text
            elif progress_type == "auto":
                action_text = auto_hint or "继续推进"
            else:
                return None

            # 记录用户行动节点
            user_node = StoryNode(
                story_id=story_id,
                parent_node_id=last_node.id if last_node else None,
                user_id=user_id,
                type="user_input",
                content=action_text,
                selected_choice=choice_id if progress_type == "choice" else None
            )
            s.add(user_node)
            await s.commit()
            await s.refresh(user_node)

            # 生成后续剧情和选项
            context = await self._build_context(story_id)
            try:
                ai_result = await asyncio.wait_for(
                    self._generate_with_json(context, action_text, progress_type),
                    timeout=20.0
                )
            except asyncio.TimeoutError:
                ai_result = {
                    "story": "剧情暂停了一下，你感觉需要做出决定。",
                    "suggestions": [{"id": 1, "text": "继续探索"}, {"id": 2, "text": "询问同伴"}],
                    "critical": False,
                    "ending": False
                }

            # 创建AI节点
            ai_node = StoryNode(
                story_id=story_id,
                parent_node_id=user_node.id,
                user_id=None,
                type="ai_output",
                content=ai_result["story"],
                choices=ai_result["suggestions"]
            )
            s.add(ai_node)
            await s.commit()
            await s.refresh(ai_node)

            return {
                "story_text": ai_result["story"],
                "suggestions": ai_result["suggestions"],
                "is_critical": ai_result.get("critical", False),
                "ending_reached": ai_result.get("ending", False),
                "node_id": ai_node.id
            }

    # ---------- 增强版生成（JSON输出） ----------
    async def _generate_with_json(self, context: str, action_text: str, action_type: str) -> dict:
        system_prompt = """你是互动叙事引擎。根据用户行动生成下一段剧情和2-4个具体行动建议。
        必须严格输出JSON格式，不要包含任何其他内容。
        
        格式：
        {
          "story": "剧情正文（300-500字）",
          "suggestions": ["具体行动1", "具体行动2", "具体行动3"],
          "critical": false,
          "ending": false
        }
        
        规则：
        1. suggestions 必须是具体的动作，比如“走向金光之路”而不是“继续”。
        2. 如果剧情到了重大转折点（如生死抉择），设置 critical=true，suggestions 应减少到2个对立选项。
        3. 如果故事达到自然结局，设置 ending=true，suggestions 可为空。
        4. 自由输入模式下，必须尊重用户的输入意图，剧情中要体现出来。
        5. 自动续写模式下，智能推进一小段，保持悬念。"""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"""当前剧情摘要：{context}
            用户行动类型：{action_type}
            用户行动内容：{action_text}
            
            请生成下一段剧情和选项，输出纯JSON：""")
        ]

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, self.llm.invoke, messages)
        raw = response.content.strip()

        # 解析JSON
        try:
            # 尝试直接解析
            data = json.loads(raw)
            story = data.get("story", "")
            suggestions_raw = data.get("suggestions", [])
            # 统一转换为字典列表
            suggestions = []
            for i, s in enumerate(suggestions_raw):
                if isinstance(s, str):
                    suggestions.append({"id": i + 1, "text": s})
                else:
                    suggestions.append(s)
            return {
                "story": story,
                "suggestions": suggestions,
                "critical": data.get("critical", False),
                "ending": data.get("ending", False)
            }
        except json.JSONDecodeError:
            # 降级处理：尝试用旧格式解析
            story, options = self._parse_response(raw)
            return {
                "story": story,
                "suggestions": options,
                "critical": False,
                "ending": False
            }


    async def continue_story(self, story_id: int, user_id: str, choice_id: int) -> Optional[Dict[str, Any]]:
        session = get_async_session()
        async with session() as s:
            # 验证故事所有权
            story = await s.get(Story, story_id)
            if not story or story.user_id != user_id or story.status != "active":
                return None

            # 获取最后节点
            result = await s.execute(
                select(StoryNode).where(StoryNode.story_id == story_id).order_by(StoryNode.created_at.desc()).limit(1)
            )
            last_node = result.scalar_one_or_none()
            if not last_node or not last_node.choices:
                return None

            selected_text = None
            for opt in last_node.choices:
                if opt["id"] == choice_id:
                    selected_text = opt["text"]
                    break
            if not selected_text:
                return None

            # 记录用户选择
            user_node = StoryNode(
                story_id=story_id,
                parent_node_id=last_node.id,
                user_id=user_id,
                type="user_input",
                content=selected_text,
                selected_choice=choice_id
            )
            s.add(user_node)
            await s.commit()
            await s.refresh(user_node)

            context = await self._build_context(story_id)
            try:
                ai_content, options = await asyncio.wait_for(
                    self._generate_story_segment(selected_text, context),
                    timeout=15.0
                )
            except asyncio.TimeoutError:
                ai_content = "故事继续发展，新的挑战即将到来……"
                options = [{"id": 1, "text": "继续"}]

            ai_node = StoryNode(
                story_id=story_id,
                parent_node_id=user_node.id,
                user_id=None,
                type="ai_output",
                content=ai_content,
                choices=options
            )
            s.add(ai_node)
            await s.commit()
            await s.refresh(ai_node)

            return {
                "id": ai_node.id,
                "type": ai_node.type,
                "content": ai_node.content,
                "choices": ai_node.choices,
                "created_at": ai_node.created_at.isoformat()
            }


    async def _generate_story_segment(self, user_action: str, context: str) -> tuple[str, list]:
        system_prompt = """你是一个富有创意的互动故事生成器。根据用户的选择，创作一段简短精彩的剧情（约150-200字），然后提供**三个具体、有吸引力**的分支选项。每个选项都必须包含明确的动作或对话，不能是模糊的表述。

        输出格式（必须严格遵守，否则系统会崩溃）：
        （剧情正文，直接叙述，不要包含任何其他内容）
        ---
        选项1：具体选项描述
        选项2：具体选项描述
        选项3：具体选项描述
    
        警告：选项必须精确以“选项1：”、“选项2：”、“选项3：”开头，不能使用其他序号。"""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"当前剧情摘要：{context}\n用户刚刚选择了：{user_action}\n请生成后续剧情和三个具体选项：")
        ]

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, self.llm.invoke, messages)
        raw_output = response.content.strip()
        logger.debug(f"AI 生成原始输出: {raw_output[:200]}...")
        story_text, options = self._parse_response(raw_output)
        return story_text, options

    # def _parse_response(self, raw: str) -> tuple[str, list]:
    #     """智能解析 AI 输出，提取剧情和选项"""
    #     # 1. 优先以“---”分隔
    #     parts = raw.split("---")
    #     if len(parts) >= 2:
    #         story_text = parts[0].strip()
    #         options_text = parts[1].strip()
    #     else:
    #         # 没有分隔符，尝试寻找选项行
    #         lines = raw.split("\n")
    #         story_lines = []
    #         option_lines = []
    #         found_option = False
    #         for line in lines:
    #             if re.match(r"^(选项|选择|分支)?\s*\d+[\.:、：]", line):
    #                 found_option = True
    #                 option_lines.append(line)
    #             elif not found_option:
    #                 story_lines.append(line)
    #             else:
    #                 option_lines.append(line)
    #         story_text = "\n".join(story_lines).strip()
    #         options_text = "\n".join(option_lines).strip()
    #
    #     # 2. 提取选项，使用多种正则匹配
    #     options = []
    #     # 匹配 “选项1：xxx” 或 “1. xxx” 或 “1、xxx” 等
    #     patterns = [
    #         r"选项\s*(\d+)\s*[：:]\s*(.+)",
    #         r"\b(\d+)\s*[\.、：:]\s*(.+)",
    #         r"\b(\d+)\s*[-–—]\s*(.+)"
    #     ]
    #     for line in options_text.split("\n"):
    #         line = line.strip()
    #         if not line:
    #             continue
    #         matched = False
    #         for pat in patterns:
    #             match = re.match(pat, line)
    #             if match:
    #                 idx = int(match.group(1))
    #                 text = match.group(2).strip()
    #                 if text and not text.startswith("选项"):  # 避免匹配到“选项1：选项2：”
    #                     options.append({"id": idx, "text": text})
    #                     matched = True
    #                     break
    #         if not matched and line:
    #             # 如果完全没有匹配到，且该行看起来像选项（非纯标点、非剧情），作为兜底
    #             if len(line) < 50 and not line.startswith("（") and not line.startswith("("):
    #                 # 简单清理，去掉可能的前缀
    #                 cleaned = re.sub(r"^[\d\.\、：:\s\-]+", "", line).strip()
    #                 if cleaned:
    #                     options.append({"id": len(options) + 1, "text": cleaned})
    #
    #     # 去重，保留唯一选项
    #     unique_options = []
    #     seen = set()
    #     for opt in options:
    #         if opt["text"] not in seen:
    #             seen.add(opt["text"])
    #             unique_options.append(opt)
    #
    #     # 3. 如果还是没有选项，生成合理的默认选项（至少三个）
    #     if len(unique_options) == 0:
    #         story_lines = story_text.split("\n")
    #         # 尝试从故事文本末尾提取看起来像行动的句子
    #         for line in reversed(story_lines):
    #             if "你决定" in line or "你选择" in line or "你走向" in line:
    #                 break
    #         # 强制生成三个有意义的默认选项
    #         unique_options = [
    #             {"id": 1, "text": "继续深入探索"},
    #             {"id": 2, "text": "改变当前策略"},
    #             {"id": 3, "text": "回头另寻出路"}
    #         ]
    #     elif len(unique_options) < 3:
    #         # 补充缺失的选项
    #         backups = ["仔细观察四周", "尝试与他人交谈", "停下脚步思考"]
    #         while len(unique_options) < 3:
    #             for b in backups:
    #                 if b not in seen:
    #                     unique_options.append({"id": len(unique_options) + 1, "text": b})
    #                     seen.add(b)
    #                     break
    #
    #     # 确保序号正确
    #     for i, opt in enumerate(unique_options):
    #         opt["id"] = i + 1
    #
    #     logger.info(f"解析得到 {len(unique_options)} 个选项: {[o['text'] for o in unique_options]}")
    #     return story_text, unique_options
    #


    # ---------- 获取故事节点（回放用） ----------


    async def get_story_nodes(self, story_id: int, user_id: str) -> Optional[List[Dict[str, Any]]]:
        session = get_async_session()
        async with session() as s:
            story = await s.get(Story, story_id)
            if not story or story.user_id != user_id:
                return None
            result = await s.execute(
                select(StoryNode).where(StoryNode.story_id == story_id).order_by(StoryNode.created_at)
            )
            nodes = result.scalars().all()
            return [
                {
                    "id": node.id,
                    "type": node.type,
                    "content": node.content,
                    "choices": node.choices,
                    "selected_choice": node.selected_choice,
                    "created_at": node.created_at.isoformat()
                }
                for node in nodes
            ]

    async def archive_story(self, story_id: int, user_id: str) -> bool:
        session = get_async_session()
        async with session() as s:
            story = await s.get(Story, story_id)
            if not story or story.user_id != user_id:
                return False
            story.status = "archived"
            await s.commit()
            return True

    async def delete_story(self, story_id: int, user_id: str) -> bool:
        session = get_async_session()
        async with session() as s:
            story = await s.get(Story, story_id)
            if not story or story.user_id != user_id:
                return False
            await s.delete(story)    # 会级联删除所有 StoryNode
            await s.commit()
            return True


    def _parse_response(self, raw: str) -> tuple[str, list]:
        """旧版解析器，作为降级方案"""
        parts = raw.split("---")
        story_text = parts[0].strip() if len(parts) >= 2 else raw
        options_text = parts[1].strip() if len(parts) >= 2 else ""
        options = []
        for line in options_text.split("\n"):
            match = re.match(r"选项(\d+)[：:]\s*(.+)", line.strip())
            if match:
                options.append({"id": int(match.group(1)), "text": match.group(2).strip()})
        if not options:
            options = [{"id": 1, "text": "继续探索"}, {"id": 2, "text": "换个思路"}, {"id": 3, "text": "稍作休息"}]
        return story_text, options

    async def _build_context(self, story_id: int) -> str:
        session = get_async_session()
        async with session() as s:
            result = await s.execute(
                select(StoryNode).where(StoryNode.story_id == story_id).order_by(StoryNode.created_at.desc()).limit(5)
            )
            recent = result.scalars().all()
            return "\n".join([f"{'【用户】' if n.type=='user_input' else '【剧情】'}：{n.content[:100]}" for n in reversed(recent)])

