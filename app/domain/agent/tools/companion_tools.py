"""
内置陪伴工具集 —— 对接现有 Service 层的 Function Calling 工具。

每个工具对应一个陪伴领域能力，LLM 在对话中按需调用。
工具通过 ToolRegistry.register_internal() 注册，随 Agent 启动加载。

上下文 (context) 规范：
  所有工具的 execute(args, context) 中的 context 字典包含：
    - user_id: str
    - role_type: str
    - emotion_svc: EmotionService
    - affection_svc: AffectionService
    - vector_memory_svc: VectorMemoryService
    - game_svc: GameService (可选)
    - story_svc: StoryService (可选)
"""
import logging
from typing import Any, Dict

from app.domain.agent.tools.base import BaseTool, ToolSpec

logger = logging.getLogger(__name__)


# ==================== 1. recall_memory — 检索用户记忆 ====================

class RecallMemoryTool(BaseTool):
    spec = ToolSpec(
        name="recall_memory",
        description="""检索关于用户的长期记忆，包括用户偏好、过往经历、重要事件等。
当用户问"你还记得...""我之前说过..."或提及过去的对话内容时调用。
返回按语义相似度排序的记忆片段。""",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "记忆检索关键词或问句，例如'用户喜欢的颜色''用户的工作'",
                },
                "max_results": {
                    "type": "integer",
                    "description": "最大返回条数",
                    "default": 3,
                },
            },
            "required": ["query"],
        },
    )

    async def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> str:
        from app.domain.memory.vector_service import VectorMemoryService

        user_id = context["user_id"]
        role_type = context.get("role_type", "")
        query = args["query"]
        max_results = args.get("max_results", 3)

        vms: VectorMemoryService = context.get("vector_memory_svc")
        if not vms:
            return "记忆服务暂不可用。"

        try:
            layers = vms.smart_retrieve(user_id, role_type, query, 0)
            formatted = VectorMemoryService.format_layers_for_prompt(layers)
            if not formatted:
                return "没有找到相关记忆。"
            return formatted
        except Exception as e:
            logger.error("recall_memory 失败: %s", e)
            return f"记忆检索失败: {e}"


# ==================== 2. save_memory — 存储对话事实 ====================

class SaveMemoryTool(BaseTool):
    spec = ToolSpec(
        name="save_memory",
        description="""存储用户在对话中透露的个人信息、偏好或重要事件。
当用户分享了关于自己的新信息时调用，例如'我的生日是6月15日''我喜欢猫'。
这些记忆会在未来的对话中被 recall_memory 检索到。""",
        parameters={
            "type": "object",
            "properties": {
                "fact": {
                    "type": "string",
                    "description": "要存储的事实内容，应是简洁明确的陈述句",
                },
                "category": {
                    "type": "string",
                    "enum": ["preference", "fact", "event", "emotion"],
                    "description": "记忆类别：preference=偏好, fact=事实, event=事件, emotion=情感",
                    "default": "fact",
                },
            },
            "required": ["fact"],
        },
    )

    async def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> str:
        user_id = context["user_id"]
        role_type = context.get("role_type", "")
        fact = args["fact"]
        category = args.get("category", "fact")

        try:
            from app.infrastructure.database import get_async_session
            from app.models.db_models import UserFact

            async_session = get_async_session()
            async with async_session() as session:
                async with session.begin():
                    session.add(UserFact(
                        user_id=user_id,
                        role_type=role_type,
                        key=category,
                        value=fact,
                    ))
            return f"已记住: {fact}"
        except Exception as e:
            logger.error("save_memory 失败: %s", e)
            return f"记忆存储失败: {e}"


# ==================== 3. read_emotion — 获取当前情绪状态 ====================

class ReadEmotionTool(BaseTool):
    spec = ToolSpec(
        name="read_emotion",
        description="""获取当前对话的情绪分析结果，包括用户情绪标签和强度。
在生成回复前调用，用于根据用户情绪调整回复语气和内容。
也用于需要知道'用户现在心情如何'的场景。""",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )

    async def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> str:
        emotion = context.get("emotion", {})
        user_input = context.get("user_input", "")

        emotion_svc = context.get("emotion_svc")
        if emotion_svc and user_input and not emotion:
            try:
                emotion = emotion_svc.analyze(user_input)
            except Exception as e:
                logger.error("read_emotion 分析失败: %s", e)

        label = emotion.get("label", "neutral")
        score = emotion.get("score", 0.5)

        emotion_descriptions = {
            "joy": "开心/喜悦", "sadness": "悲伤/难过", "anger": "愤怒/生气",
            "fear": "害怕/恐惧", "surprise": "惊讶/意外", "love": "喜爱/温暖",
            "gratitude": "感激/感恩", "loneliness": "孤独/寂寞", "anxiety": "焦虑/不安",
            "boredom": "无聊/乏味", "disappointment": "失望/沮丧", "hope": "期待/希望",
            "envy": "羡慕/嫉妒", "guilt": "愧疚/自责", "confusion": "困惑/迷茫",
            "sarcasm": "讽刺/挖苦", "mockery": "嘲弄/戏谑", "despair": "绝望/无助",
            "neutral": "平静/中性",
        }
        desc = emotion_descriptions.get(label, label)
        return f"当前用户情绪: {desc} (置信度: {score:.0%})"


# ==================== 4. get_affection — 查询好感度 ====================

class GetAffectionTool(BaseTool):
    spec = ToolSpec(
        name="get_affection",
        description="""查询用户与当前角色的好感度四维数据（亲密度/信任度/趣味度/成长度）。
当用户问"我们关系怎么样""你有多了解我"或需要展示关系状态时调用。""",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )

    async def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> str:
        user_id = context["user_id"]
        role_type = context.get("role_type", "")
        affection_svc = context.get("affection_svc")

        if not affection_svc:
            return "好感度服务暂不可用。"

        try:
            aff = await affection_svc.get(user_id, role_type)
            level = await affection_svc.get_unlock_state(user_id, role_type)
            return (
                f"亲密度: {aff['intimacy']:.0f}/100 | "
                f"信任度: {aff['trust']:.0f}/100 | "
                f"趣味度: {aff['fun']:.0f}/100 | "
                f"成长度: {aff['growth']:.0f}/100 | "
                f"关系等级: Lv.{level.get('level', 0)}"
            )
        except Exception as e:
            logger.error("get_affection 失败: %s", e)
            return f"好感度查询失败: {e}"


# ==================== 5. update_affection — 更新好感度 ====================

class UpdateAffectionTool(BaseTool):
    spec = ToolSpec(
        name="update_affection",
        description="""根据对话内容调整好感度。在对话结束后或用户做出有意义的互动后调用。
delta 四个维度均为可选，正值增加，负值减少（范围 0-100）。""",
        parameters={
            "type": "object",
            "properties": {
                "intimacy": {
                    "type": "number", "description": "亲密度变化量（可正可负）"
                },
                "trust": {
                    "type": "number", "description": "信任度变化量"
                },
                "fun": {
                    "type": "number", "description": "趣味度变化量"
                },
                "growth": {
                    "type": "number", "description": "成长度变化量"
                },
                "reason": {
                    "type": "string", "description": "变化原因的简短说明"
                },
            },
            "required": [],
        },
    )

    async def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> str:
        user_id = context["user_id"]
        role_type = context.get("role_type", "")
        affection_svc = context.get("affection_svc")

        if not affection_svc:
            return "好感度服务暂不可用。"

        delta = {
            k: args[k] for k in ["intimacy", "trust", "fun", "growth"]
            if k in args and args[k] is not None
        }
        reason = args.get("reason", "")

        if not delta:
            return "未指定变化量，好感度未更新。"

        try:
            await affection_svc.update(user_id, role_type, delta)
            parts = [f"{k}: {v:+.1f}" for k, v in delta.items()]
            msg = f"好感度已更新 ({', '.join(parts)})"
            if reason:
                msg += f"，原因: {reason}"
            return msg
        except Exception as e:
            logger.error("update_affection 失败: %s", e)
            return f"好感度更新失败: {e}"


# ==================== 6. check_achievements — 检查成就进度 ====================

class CheckAchievementsTool(BaseTool):
    spec = ToolSpec(
        name="check_achievements",
        description="""查询用户的游戏化成就进度，包括已解锁和进行中的成就。
当用户问'我有什么成就''还有什么任务'或需要激励用户时调用。""",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )

    async def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> str:
        user_id = context["user_id"]
        game_svc = context.get("game_svc")

        if not game_svc:
            return "游戏服务暂不可用。"

        try:
            achievements = await game_svc.get_achievements(user_id)
            if not achievements:
                return "暂无成就记录。"

            completed = [a for a in achievements if a.get("completed")]
            in_progress = [a for a in achievements if not a.get("completed")]

            lines = []
            if completed:
                lines.append(f"已解锁成就 ({len(completed)}):")
                for a in completed[:5]:
                    lines.append(f"  🏆 {a['name']} — {a['description']}")
            if in_progress:
                lines.append(f"进行中的成就 ({len(in_progress)}):")
                for a in in_progress[:5]:
                    pct = min(100, int(a.get("progress", 0) / a.get("threshold", 1) * 100))
                    lines.append(f"  ⏳ {a['name']} — {pct}%")
            return "\n".join(lines) if lines else "暂无成就进度。"
        except Exception as e:
            logger.error("check_achievements 失败: %s", e)
            return f"成就查询失败: {e}"


# ==================== 7. do_game_action — 执行游戏动作 ====================

class DoGameActionTool(BaseTool):
    spec = ToolSpec(
        name="do_game_action",
        description="""执行一个游戏养成动作，如完成每日任务、兑换皮肤等。
当用户说'做任务''完成每日''换个皮肤'等涉及游戏化系统的操作时调用。""",
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["complete_task", "get_tasks", "get_skins", "equip_skin"],
                    "description": "游戏动作类型: complete_task=完成任务, get_tasks=查看每日任务, get_skins=查看皮肤, equip_skin=装备皮肤",
                },
                "task_id": {
                    "type": "integer",
                    "description": "任务ID（action=complete_task时需要）",
                },
                "skin_id": {
                    "type": "integer",
                    "description": "皮肤ID（action=equip_skin时需要）",
                },
            },
            "required": ["action"],
        },
    )

    async def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> str:
        user_id = context["user_id"]
        role_type = context.get("role_type", "")
        game_svc = context.get("game_svc")

        if not game_svc:
            return "游戏服务暂不可用。"

        action = args["action"]

        try:
            if action == "get_tasks":
                tasks = await game_svc.get_daily_tasks(user_id, role_type)
                if not tasks:
                    return "今日暂无任务。"
                lines = ["今日任务:"]
                for t in tasks:
                    status = "✅" if t.get("completed") else "⬜"
                    lines.append(f"  {status} {t['name']} — {t['description']} (奖励: +{t.get('reward_intimacy', 0)}亲密度)")
                return "\n".join(lines)

            elif action == "complete_task":
                task_id = args.get("task_id")
                if not task_id:
                    return "请指定要完成的任务ID。"
                result = await game_svc.complete_daily_task(user_id, role_type, task_id)
                if result.get("success"):
                    return f"任务完成! 亲密度 +{result.get('reward_intimacy', 0)}"
                return f"任务完成失败: {result.get('message', '未知错误')}"

            elif action == "get_skins":
                skins = await game_svc.get_skins(user_id, role_type)
                if not skins:
                    return "该角色暂无可用的皮肤。"
                lines = ["可用皮肤:"]
                for s in skins:
                    status = "✅已解锁" if s.get("unlocked") else "🔒未解锁"
                    equip = " 👈当前装备" if s.get("equipped") else ""
                    lines.append(f"  {status} {s['name']} — {s.get('description', '')}{equip}")
                return "\n".join(lines)

            elif action == "equip_skin":
                skin_id = args.get("skin_id")
                if not skin_id:
                    return "请指定要装备的皮肤ID。"
                result = await game_svc.equip_skin(user_id, role_type, skin_id)
                if result.get("success"):
                    return "皮肤已装备!"
                return "皮肤装备失败。"

            return f"未知的游戏动作: {action}"

        except Exception as e:
            logger.error("do_game_action 失败: %s", e)
            return f"游戏动作执行失败: {e}"


# ==================== 8. progress_story — 推进互动叙事 ====================

class ProgressStoryTool(BaseTool):
    spec = ToolSpec(
        name="progress_story",
        description="""推进互动叙事（共创故事），包括开始新故事、做出选择、继续故事。
当用户说'讲故事''继续故事''开始故事'等叙事相关内容时调用。""",
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["get_starters", "start_story", "make_choice", "free_text"],
                    "description": "叙事动作: get_starters=查看可选故事, start_story=开始故事, make_choice=做出选择, free_text=自由输入",
                },
                "category": {
                    "type": "string",
                    "description": "故事类别筛选（action=get_starters时可选）",
                },
                "title": {
                    "type": "string",
                    "description": "故事标题（action=start_story时需要）",
                },
                "story_id": {
                    "type": "integer",
                    "description": "故事ID（action=make_choice/free_text时需要）",
                },
                "choice_id": {
                    "type": "integer",
                    "description": "选择ID（action=make_choice时需要）",
                },
                "text": {
                    "type": "string",
                    "description": "用户自由输入的文本（action=free_text时需要）",
                },
            },
            "required": ["action"],
        },
    )

    async def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> str:
        user_id = context["user_id"]
        role_type = context.get("role_type", "")
        story_svc = context.get("story_svc")

        if not story_svc:
            return "叙事服务暂不可用。"

        action = args["action"]

        try:
            if action == "get_starters":
                starters = await story_svc.get_starters(args.get("category"))
                if not starters:
                    return "暂无可用的故事起点。"
                lines = ["可选故事:"]
                for s in starters:
                    lines.append(f"  📖 {s['category']} — {s['title']}: {s['description']}")
                return "\n".join(lines)

            elif action == "start_story":
                title = args.get("title", "")
                starters = await story_svc.get_starters()
                matched = [s for s in starters if s["title"] == title]
                if not matched:
                    titles = [s["title"] for s in starters]
                    return f"未找到故事'{title}'，可用: {', '.join(titles)}"
                s = matched[0]
                result = await story_svc.start_story(
                    user_id, role_type, s["title"],
                    s["starter_text"], s["options"],
                )
                node = result.get("first_node", {})
                lines = [
                    f"📖 故事开始: {s['title']}",
                    f"\n{node.get('content', '')}",
                    "\n你的选择:",
                ]
                for opt in node.get("choices", []):
                    lines.append(f"  [{opt['id']}] {opt['text']}")
                return "\n".join(lines)

            elif action == "make_choice":
                story_id = args.get("story_id")
                choice_id = args.get("choice_id")
                if not story_id or not choice_id:
                    return "请提供 story_id 和 choice_id。"
                result = await story_svc.progress_story(
                    story_id, user_id, "choice", choice_id=choice_id,
                )
                if not result:
                    return "故事推进失败，请检查故事ID是否正确。"
                lines = [result.get("story_text", "")]
                if result.get("suggestions"):
                    lines.append("\n接下来:")
                    for opt in result["suggestions"]:
                        lines.append(f"  [{opt.get('id', '?')}] {opt.get('text', '')}")
                return "\n".join(lines)

            elif action == "free_text":
                story_id = args.get("story_id")
                text = args.get("text", "")
                if not story_id or not text:
                    return "请提供 story_id 和 text。"
                result = await story_svc.progress_story(
                    story_id, user_id, "free_text", free_text=text,
                )
                if not result:
                    return "故事推进失败。"
                lines = [result.get("story_text", "")]
                if result.get("suggestions"):
                    lines.append("\n接下来:")
                    for opt in result["suggestions"]:
                        lines.append(f"  [{opt.get('id', '?')}] {opt.get('text', '')}")
                return "\n".join(lines)

            return f"未知的叙事动作: {action}"

        except Exception as e:
            logger.error("progress_story 失败: %s", e)
            return f"叙事操作失败: {e}"


# ==================== 9. query_knowledge — RAG 知识检索 ====================

class QueryKnowledgeTool(BaseTool):
    spec = ToolSpec(
        name="query_knowledge",
        description="""从知识库中检索信息，用于回答需要外部知识的问题。
当用户问及动漫、游戏、科技等领域的知识，或需要引经据典时调用。
注意：这是通用知识检索，不是用户个人记忆（那个用 recall_memory）。""",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "知识检索查询语句",
                },
                "max_results": {
                    "type": "integer",
                    "description": "最大返回条数",
                    "default": 3,
                },
            },
            "required": ["query"],
        },
    )

    async def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> str:
        from app.infrastructure.chroma import get_chroma_client
        from langchain_community.embeddings import DashScopeEmbeddings

        query = args["query"]
        max_results = args.get("max_results", 3)
        settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()

        try:
            # 1. 用阿里云 DashScope text-embedding-v4 计算查询向量
            embeddings = DashScopeEmbeddings(
                model=settings.EMBED_MODEL,
                dashscope_api_key=settings.DASHSCOPE_API_KEY,
            )
            query_vector = embeddings.embed_query(query)

            # 2. ChromaDB 查询 —— 传向量不传文本，不触发本地 ONNX 下载
            client = get_chroma_client()
            collection = client.get_or_create_collection(
                "knowledge_base",
                metadata={"hnsw:space": "cosine"},
            )
            results = collection.query(
                query_embeddings=[query_vector],
                n_results=min(max_results, 10),
            )
            documents = results.get("documents", [[]])[0]
            if not documents:
                return f"未找到与'{query}'相关的知识。"
            return "\n---\n".join(documents[:max_results])
        except Exception as e:
            logger.error("query_knowledge 失败: %s", e)
            return f"知识检索失败: {e}"


# ==================== 10. set_role_style — 调整角色风格 ====================

class SetRoleStyleTool(BaseTool):
    spec = ToolSpec(
        name="set_role_style",
        description="""调整当前对话角色的说话风格或切换到其他角色。
当用户说'换个角色''换种风格''想和XX聊天'时调用。""",
        parameters={
            "type": "object",
            "properties": {
                "role_name": {
                    "type": "string",
                    "description": "目标角色名称，如'日系动漫型''高冷御姐型''傲娇辣妹型'等",
                },
                "style_modifier": {
                    "type": "string",
                    "description": "额外的风格微调指令（可选），如'更温柔一点''多用颜文字'",
                },
            },
            "required": ["role_name"],
        },
    )

    async def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> str:
        from app.domain.roles.catalog import RoleCatalog

        role_name = args["role_name"]
        style_modifier = args.get("style_modifier", "")

        try:
            role = RoleCatalog.get_role(role_name)
            if not role:
                available = ", ".join(RoleCatalog.get_all_names())
                return f"未找到角色'{role_name}'。可用角色: {available}"

            msg = f"已切换至角色: {role.name} — {role.persona}"
            if style_modifier:
                msg += f" (风格微调: {style_modifier})"
            return msg
        except Exception as e:
            logger.error("set_role_style 失败: %s", e)
            return f"角色切换失败: {e}"


# ==================== 注册函数 ====================

def register_all_companion_tools(registry) -> None:
    """将所有内置陪伴工具注册到 ToolRegistry。

    在 Agent 初始化时调用一次。配合 VectorMemoryService 等 service 引用，
    各工具通过 execute() 的 context 参数接收运行时依赖。

    Args:
        registry: ToolRegistry 实例
    """
    registry.register_internal(RecallMemoryTool())
    registry.register_internal(SaveMemoryTool())
    registry.register_internal(ReadEmotionTool())
    registry.register_internal(GetAffectionTool())
    registry.register_internal(UpdateAffectionTool())
    registry.register_internal(CheckAchievementsTool())
    registry.register_internal(DoGameActionTool())
    registry.register_internal(ProgressStoryTool())
    registry.register_internal(QueryKnowledgeTool())
    registry.register_internal(SetRoleStyleTool())
    logger.info(
        "已注册 %d 个内置陪伴工具: %s",
        registry.tool_count,
        registry.get_tool_names(),
    )
