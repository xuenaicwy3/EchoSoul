import asyncio
import json
import logging
from typing import List, Dict, Optional
from datetime import datetime, timezone
from sqlalchemy import select, desc, func
from app.database import get_async_session
from app.models.db_models import UserFact, EmotionRecord, RelationshipMilestone, UserMemorySummary
from app.config import Settings
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from collections import Counter

from app.redis_client import get_redis_client

logger = logging.getLogger(__name__)

# 结构化记忆文本最大长度（字符），超出后会进行压缩
MAX_MEMORY_TEXT_LENGTH = 1200


class AffectiveMemoryService:
    def __init__(self, settings: Settings):
        self.settings = settings
        # 用于提取事实的轻量 LLM
        self.extract_llm = init_chat_model(
            model=settings.LLM_MODEL,
            model_provider="openai",
            temperature=0.1,
            max_tokens=200,
            api_key=settings.DASHSCOPE_API_KEY,
            base_url=settings.DASHSCOPE_BASE_URL,
        )
        # 摘要生成 / 压缩用模型（可配置为更大模型以提升质量）
        self.summary_llm = init_chat_model(
            model=settings.LLM_MODEL,
            model_provider="openai",
            temperature=0.2,
            max_tokens=300,
            api_key=settings.DASHSCOPE_API_KEY,
            base_url=settings.DASHSCOPE_BASE_URL,
        )


    # ==================== 事实层 ====================
    async def add_fact(self, user_id: str, role_type: str, key: str, value: str, source: str = "extracted"):
        try:
            session = get_async_session()
        except RuntimeError:
            logger.warning("数据库未初始化，跳过事实添加")
            return False
        async with session() as s:
            result = await s.execute(
                select(UserFact).where(
                    UserFact.user_id == user_id,
                    UserFact.role_type == role_type,
                    UserFact.key == key
                )
            )
            fact = result.scalar_one_or_none()
            if fact:
                fact.value = value
                fact.source = source
                fact.updated_at = datetime.now(timezone.utc)
                logger.info(f"事实更新: {key}={value} (用户={user_id[:8]}, 角色={role_type})")
            else:
                fact = UserFact(user_id=user_id, role_type=role_type, key=key, value=value, source=source)
                s.add(fact)
                logger.info(f"事实新增: {key}={value} (用户={user_id[:8]}, 角色={role_type})")
            await s.commit()
            return True

    async def get_facts(self, user_id: str, role_type: str) -> List[Dict]:
        try:
            session = get_async_session()
        except RuntimeError:
            logger.warning("数据库未初始化，返回空事实列表")
            return []
        async with session() as s:
            result = await s.execute(
                select(UserFact)
                .where(UserFact.user_id == user_id, UserFact.role_type == role_type)
                .order_by(UserFact.key)
            )
            facts = result.scalars().all()
            logger.info(f"加载事实: user={user_id[:8]}, role={role_type}, 共 {len(facts)} 条")
            return [{"key": f.key, "value": f.value, "source": f.source} for f in facts]

    async def extract_facts_from_conversation(self, user_id: str, role_type: str,
                                              user_msg: str, ai_reply: str):
        """从对话中提取用户事实，并更新数据库"""
        try:
            session = get_async_session()
        except RuntimeError:
            logger.warning("数据库未初始化，跳过事实提取")
            return
        try:
            prompt = f"""分析下面的对话，提取关于用户的重要个人信息（如姓名、生日、喜好、讨厌的事物、职业、宠物等），
            以 JSON 格式返回，key 为信息类型，value 为信息内容。如果没有明确信息则返回空 JSON。只输出 JSON，不要有任何其他文字。

            用户: {user_msg}
            角色: {ai_reply}

            JSON:"""
            messages = [HumanMessage(content=prompt)]
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(None, self.extract_llm.invoke, messages)
            raw = response.content.strip()
            if raw.startswith("```json"): raw = raw[7:]
            if raw.endswith("```"): raw = raw[:-3]
            data = json.loads(raw)
            if isinstance(data, dict):
                for key, value in data.items():
                    if value and str(value).strip():
                        await self.add_fact(user_id, role_type, key, str(value), "extracted")
                logger.info(f"事实提取成功: {raw[:50]}")
            else:
                logger.info(f"事实提取未发现有效信息: {raw[:50]}")

        except Exception as e:
            logger.error(f"事实提取失败: {e}")

    # ==================== 情感层 ====================
    async def record_emotion(self, user_id: str, role_type: str,
                             label: str, score: float, message: str = None):
        try:
            session = get_async_session()
        except RuntimeError:
            logger.warning("数据库未初始化，跳过情感记录")
            return
        async with session() as s:
            record = EmotionRecord(
                user_id=user_id, role_type=role_type,
                label=label, score=score, message=message
            )
            s.add(record)
            await s.commit()
            logger.info(f"情感记录: label={label}, score={score:.2f}, user={user_id[:8]}, role={role_type}")

    async def get_emotion_trend(self, user_id: str, role_type: str, limit: int = 30) -> Dict:
        try:
            session = get_async_session()
        except RuntimeError:
            logger.warning("数据库未初始化，返回默认情感趋势")
            return {"records": [], "dominant_emotion": "neutral", "trend": "平稳"}
        async with session() as s:
            result = await s.execute(
                select(EmotionRecord)
                .where(EmotionRecord.user_id == user_id, EmotionRecord.role_type == role_type)
                .order_by(desc(EmotionRecord.created_at))
                .limit(limit)
            )
            records = result.scalars().all()
            records = list(reversed(records))

            if not records:
                logger.info(f"情感趋势: user={user_id[:8]}, role={role_type}, 暂无记录")
                return {"records": [], "dominant_emotion": "neutral", "trend": "平稳"}

            labels = [r.label for r in records]
            dominant = Counter(labels).most_common(1)[0][0]

            if len(records) >= 10:
                earlier_avg = sum(r.score for r in records[:5]) / 5
                later_avg = sum(r.score for r in records[-5:]) / 5
                if later_avg > earlier_avg + 0.2:
                    trend = "上扬"
                elif later_avg < earlier_avg - 0.2:
                    trend = "低落"
                else:
                    trend = "平稳"
            else:
                trend = "数据不足"

            logger.info(
                f"情感趋势: user={user_id[:8]}, role={role_type}, dominant={dominant}, trend={trend}, records={len(records)}")
            return {
                "records": [{"label": r.label, "score": r.score, "time": r.created_at.isoformat()} for r in records],
                "dominant_emotion": dominant,
                "trend": trend
            }

    # ==================== 关系层 ====================
    async def add_milestone(self, user_id: str, role_type: str, event: str, event_type: str, details: str = None):
        try:
            session = get_async_session()
        except RuntimeError:
            logger.warning("数据库未初始化，跳过里程碑添加")
            return
        async with session() as s:
            milestone = RelationshipMilestone(
                user_id=user_id, role_type=role_type,
                event=event, event_type=event_type, details=details
            )
            s.add(milestone)
            await s.commit()
            logger.info(f"里程碑新增: {event} (type={event_type}) user={user_id[:8]}, role={role_type}")

    async def get_milestones(self, user_id: str, role_type: str) -> List[Dict]:
        try:
            session = get_async_session()
        except RuntimeError:
            logger.warning("数据库未初始化，返回空里程碑列表")
            return []
        async with session() as s:
            result = await s.execute(
                select(RelationshipMilestone)
                .where(RelationshipMilestone.user_id == user_id, RelationshipMilestone.role_type == role_type)
                .order_by(desc(RelationshipMilestone.created_at))
            )
            milestones = result.scalars().all()
            logger.info(f"加载里程碑: user={user_id[:8]}, role={role_type}, 共 {len(milestones)} 条")
            return [
                {"event": m.event, "event_type": m.event_type, "time": m.created_at.isoformat()}
                for m in milestones
            ]

    async def check_and_add_milestones(self, user_id: str, role_type: str, intimacy: float):
        """根据亲密度自动添加里程碑"""
        milestones = await self.get_milestones(user_id, role_type)
        existing_types = {m['event_type'] for m in milestones}

        if intimacy >= 30 and "intimacy_30" not in existing_types:
            await self.add_milestone(user_id, role_type, "亲密度达到30", "intimacy_30", "关系逐渐熟悉")
        if intimacy >= 50 and "intimacy_50" not in existing_types:
            await self.add_milestone(user_id, role_type, "亲密度达到50", "intimacy_50", "成为亲密伙伴")
        if intimacy >= 80 and "intimacy_80" not in existing_types:
            await self.add_milestone(user_id, role_type, "亲密度达到80", "intimacy_80", "深厚羁绊")


    # ==================== 记忆摘要（迭代更新 + 智能触发） ====================
    async def get_memory_summary(self, user_id: str, role_type: str) -> str:
        """获取或生成用户画像摘要，支持基于旧摘要迭代更新"""
        try:
            session = get_async_session()
        except RuntimeError:
            return ""

        async with session() as s:
            # 查询现有摘要
            result = await s.execute(
                select(UserMemorySummary)
                .where(UserMemorySummary.user_id == user_id, UserMemorySummary.role_type == role_type)
                .order_by(desc(UserMemorySummary.updated_at)).limit(1)
            )
            cached = result.scalar_one_or_none()

            # 统计各维度数据量，用于触发重生成
            fact_count = (await s.execute(select(func.count()).select_from(UserFact).where(
                UserFact.user_id == user_id, UserFact.role_type == role_type))).scalar() or 0
            emotion_count = (await s.execute(select(func.count()).select_from(EmotionRecord).where(
                EmotionRecord.user_id == user_id, EmotionRecord.role_type == role_type))).scalar() or 0
            milestone_count = (await s.execute(select(func.count()).select_from(RelationshipMilestone).where(
                RelationshipMilestone.user_id == user_id, RelationshipMilestone.role_type == role_type))).scalar() or 0

            # 判断是否需要重生成：
            # 1. 没有缓存
            # 2. 新事实数 > 缓存时的事实数 + 3
            # 3. 新情感记录数 > 缓存时的情感记录数 + 10
            # 4. 新里程碑数 > 缓存时的里程碑数
            need_regenerate = not cached
            if cached:
                if fact_count > (cached.fact_count or 0) + 3:
                    need_regenerate = True
                if emotion_count > (cached.emotion_count or 0) + 10:
                    need_regenerate = True
                if milestone_count > (cached.milestone_count or 0):
                    need_regenerate = True
                # 超过24小时也强制刷新
                if (datetime.now(timezone.utc) - cached.updated_at).total_seconds() > 86400:
                    need_regenerate = True

            if not need_regenerate and cached:
                logger.info("无需更新摘要，使用缓存")
                return cached.summary

            # 准备生成材料
            facts = await self.get_facts(user_id, role_type)
            trend = await self.get_emotion_trend(user_id, role_type, limit=10)
            milestones = await self.get_milestones(user_id, role_type)

            fact_text = "\n".join([f"- {f['key']}: {f['value']}" for f in facts]) if facts else "暂无"
            emotion_text = f"主导情绪: {trend['dominant_emotion']}，趋势: {trend['trend']}" if trend['records'] else "暂无"
            milestone_text = "\n".join([f"- {m['event']} ({m['time'][:10]})" for m in milestones[:5]]) if milestones else "暂无"

            # 构建生成 / 更新提示词
            if cached and cached.summary:
                # 迭代更新模式
                prompt = f"""你是一位用户画像维护助手。下面是一份已有的用户画像摘要，以及最近发生的新信息。请基于这些内容更新画像摘要，确保保留重要历史信息，同时融入新变化。输出不超过200字。

                已有画像：
                {cached.summary}
                
                最新资料：
                - 事实：{fact_text}
                - 近期情绪：{emotion_text}
                - 重要事件：{milestone_text}
                
                请输出更新后的用户画像摘要（不要编号，直接叙述）："""
            else:
                # 首次生成模式
                prompt = f"""请根据下面的用户信息，生成一段简短的用户画像摘要（不超过200字），用于AI角色与用户的对话上下文中。

                用户基本资料：
                {fact_text}
                
                用户近期情绪状态：
                {emotion_text}
                
                重要关系事件：
                {milestone_text}
                
                请用流畅的自然语言概括，不要编号，直接输出摘要内容。"""

            try:
                messages = [HumanMessage(content=prompt)]
                loop = asyncio.get_running_loop()
                response = await loop.run_in_executor(None, self.summary_llm.invoke, messages)
                new_summary = response.content.strip()

                # 更新缓存
                if cached:
                    cached.summary = new_summary
                    cached.emotion_count = emotion_count
                    cached.fact_count = fact_count
                    cached.milestone_count = milestone_count
                    cached.updated_at = datetime.now(timezone.utc)
                else:
                    # 注意：UserMemorySummary 模型需要扩展字段 fact_count, milestone_count
                    # 如果还没有这些字段，请先在 db_models.py 中添加
                    cached = UserMemorySummary(
                        user_id=user_id, role_type=role_type,
                        summary=new_summary, emotion_count=emotion_count,
                        fact_count=fact_count, milestone_count=milestone_count
                    )
                    s.add(cached)
                await s.commit()
                logger.info(f"记忆摘要已{'更新' if cached else '生成'}，长度={len(new_summary)}")
                return new_summary
            except Exception as e:
                logger.error(f"摘要生成失败: {e}")
                return cached.summary if cached else ""

    # ==================== 结构化记忆缓存（带上下文压缩） ====================
    async def cache_structured_memory(self, user_id: str, role_type: str,
                                      facts: Optional[List[Dict]] = None,
                                      trend: Optional[Dict] = None,
                                      milestones: Optional[List[Dict]] = None,
                                      summary: Optional[str] = None):
        """聚合结构化记忆并写入 Redis，支持复用数据, 若文本过长则进行智能压缩"""
        if facts is None:
            facts = await self.get_facts(user_id, role_type)
        if trend is None:
            trend = await self.get_emotion_trend(user_id, role_type, limit=5)
        if milestones is None:
            milestones = await self.get_milestones(user_id, role_type)
        if summary is None:
            summary = await self.get_memory_summary(user_id, role_type)

        # 构建原始记忆文本
        parts = []

        # 事实
        if facts:
            fact_lines = "\n".join([f"- {f['key']}: {f['value']}" for f in facts])
            parts.append(f"关于用户的已知信息：\n{fact_lines}")

        # 情感趋势
        if trend and trend['records']:
            recent = ", ".join([f"{r['label']}({r['score']:.1f})" for r in trend['records'][-3:]])
            parts.append(f"用户最近情绪: {recent}，主导情绪: {trend['dominant_emotion']}，趋势: {trend['trend']}")

        # 里程碑（补上，只取最近3条，避免过长）
        if milestones:
            milestone_text = "重要事件：\n" + "\n".join(
                [f"- {m['event']} ({m['time'][:10]})" for m in milestones[:3]])
            parts.append(milestone_text)

        # 用户画像摘要
        if summary:
            parts.append(f"【用户画像摘要】{summary}")

        raw_text = "\n".join(parts)

        # 智能压缩：如果总长度超过阈值，则只保留摘要 + 情感趋势，舍弃详细事实和里程碑
        if len(raw_text) > MAX_MEMORY_TEXT_LENGTH and summary:
            # 策略：仅保留摘要和情感趋势，舍弃详细事实列表
            compressed = []
            if trend and trend['records']:
                recent = ", ".join([f"{r['label']}({r['score']:.1f})" for r in trend['records'][-3:]])
                compressed.append(f"用户最近情绪: {recent}，主导情绪: {trend['dominant_emotion']}")
            if summary:
                compressed.append(f"【用户画像摘要】{summary}")
            raw_text = "\n".join(compressed)

        # 若仍然超标，动用轻量 LLM 二次压缩
        if len(raw_text) > MAX_MEMORY_TEXT_LENGTH:
            raw_text = await self._llm_compress(raw_text)

        if raw_text:
            r = get_redis_client()
            await r.setex(f"structured_memory:{user_id}:{role_type}", 3600, raw_text)
            logger.info(f"结构化记忆已缓存 (长度={len(raw_text)})")
            logger.info(f"结构化记忆已缓存: user={user_id[:8]}, role={role_type}, raw_text={raw_text}")

    async def _llm_compress(self, text: str) -> str:
        """使用轻量 LLM 压缩文本，保留关键信息"""
        try:
            messages = [
                SystemMessage(content="请将以下信息压缩为一段不超过150字的摘要，保留重要的事实和情感倾向。"),
                HumanMessage(content=text)
            ]
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(None, self.summary_llm.invoke, messages)
            compressed = response.content.strip()
            return compressed if compressed else text[:MAX_MEMORY_TEXT_LENGTH]
        except Exception as e:
            logger.error(f"LLM压缩失败: {e}")
            return text[:MAX_MEMORY_TEXT_LENGTH]



    # ==================== Redis 缓存 ====================
    # async def cache_structured_memory(self, user_id: str, role_type: str):
    #     """聚合所有结构化记忆并缓存到 Redis，供 Celery 任务快速读取
    #        结构化记忆格式如下（例如：）
    #       关于用户的已知信息：
    #         - 喜好: 喜欢看动漫《学战都市》，尤其喜欢角色尤莉丝、刀藤绮凛、沙沙宫纱夜
    #         用户最近情绪: love(0.9), love(0.9), love(0.9)，主导情绪: love，趋势: 上扬/平稳/低落/数据不足
    #         重要事件：
    #         - 亲密度达到80 (2026-06-04)
    #         - 亲密度达到50 (2026-06-04)
    #         - 亲密度达到30 (2026-06-04)
    #         【用户画像摘要】你发自内心地喜欢尤莉丝，这份情感是你近期最鲜明的动力。今天你们的亲密度一路攀升，先后突破了30、50，最终达到80，
    #         关系进展相当显著。你整体沉浸在一种平稳的喜悦之中，心情明朗而安定
    #     """
    #     parts = []
    #     facts = await self.get_facts(user_id, role_type)
    #     if facts:
    #         fact_lines = "\n".join([f"- {f['key']}: {f['value']}" for f in facts])
    #         parts.append(f"关于用户的已知信息：\n{fact_lines}")
    #
    #     trend = await self.get_emotion_trend(user_id, role_type, limit=5)
    #     if trend['records']:
    #         recent = ", ".join([f"{r['label']}({r['score']:.1f})" for r in trend['records'][-3:]])
    #         parts.append(f"用户最近情绪: {recent}，主导情绪: {trend['dominant_emotion']}，趋势: {trend['trend']}")
    #
    #     milestones = await self.get_milestones(user_id, role_type)
    #     if milestones:
    #         milestone_text = "重要事件：\n" + "\n".join(
    #             [f"- {m['event']} ({m['time'][:10]})" for m in milestones[:3]])
    #         parts.append(milestone_text)
    #
    #     summary = await self.get_memory_summary(user_id, role_type)
    #     if summary:
    #         parts.append(f"【用户画像摘要】{summary}")
    #
    #     mem_text = "\n".join(parts)
    #     if mem_text:
    #         r = get_redis_client()
    #         await r.setex(f"structured_memory:{user_id}:{role_type}", 3600, mem_text)
    #         logger.info(f"结构化记忆已缓存: user={user_id[:8]}, role={role_type}")