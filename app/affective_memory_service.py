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
from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)


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
            prompt = f"""分析下面的对话，提取关于用户的重要个人信息（如姓名、生日、喜好、讨厌的事物、职业、宠物等），以 JSON 格式返回，key 为信息类型，value 为信息内容。如果没有明确信息则返回空 JSON。只输出 JSON，不要有任何其他文字。

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
            else:
                logger.debug(f"事实提取未发现有效信息: {raw[:50]}")
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

            from collections import Counter
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


    # ==================== 记忆摘要 ====================
    async def get_memory_summary(self, user_id: str, role_type: str) -> str:
        """获取或生成记忆摘要（带缓存，避免频繁调用LLM）"""
        try:
            session = get_async_session()
        except RuntimeError:
            logger.warning("数据库未初始化，返回空摘要")
            return ""

        async with session() as s:
            # 1. 查询现有摘要
            result = await s.execute(
                select(UserMemorySummary)
                .where(UserMemorySummary.user_id == user_id, UserMemorySummary.role_type == role_type)
                .order_by(desc(UserMemorySummary.updated_at))
                .limit(1)
            )
            cached = result.scalar_one_or_none()

            # 2. 获取当前情感记录总数，判断是否需要重新生成
            count_result = await s.execute(
                select(func.count()).select_from(EmotionRecord).where(
                    EmotionRecord.user_id == user_id,
                    EmotionRecord.role_type == role_type
                )
            )
            current_emotion_count = count_result.scalar() or 0

            # 缓存条件：摘要存在、情感记录无新增超过5条、距离上次生成不到1小时
            if cached and cached.emotion_count and current_emotion_count - cached.emotion_count <= 5:
                if cached.updated_at and (datetime.now(timezone.utc) - cached.updated_at).total_seconds() < 3600:
                    logger.info(f"使用缓存的记忆摘要: user={user_id[:8]}")
                    return cached.summary

            # 3. 重新生成摘要
            facts = await self.get_facts(user_id, role_type)
            trend = await self.get_emotion_trend(user_id, role_type, limit=10)
            milestones = await self.get_milestones(user_id, role_type)

            # 构建 prompt
            fact_text = "\n".join([f"- {f['key']}: {f['value']}" for f in facts]) if facts else "暂无"
            emotion_text = f"主导情绪: {trend['dominant_emotion']}，趋势: {trend['trend']}" if trend[
                'records'] else "暂无"
            milestone_text = "\n".join(
                [f"- {m['event']} ({m['time'][:10]})" for m in milestones[:3]]) if milestones else "暂无"

            prompt = f"""请根据下面的用户信息，生成一段简短的用户画像摘要（不超过150字），用于AI角色与用户的对话上下文中。

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
                response = await loop.run_in_executor(None, self.extract_llm.invoke, messages)
                summary = response.content.strip()

                # 存入缓存
                if cached:
                    cached.summary = summary
                    cached.emotion_count = current_emotion_count
                    cached.updated_at = datetime.now(timezone.utc)
                else:
                    cached = UserMemorySummary(
                        user_id=user_id, role_type=role_type,
                        summary=summary, emotion_count=current_emotion_count
                    )
                    s.add(cached)
                await s.commit()
                logger.info(f"记忆摘要已更新: user={user_id[:8]}, length={len(summary)}")
                return summary
            except Exception as e:
                logger.error(f"生成记忆摘要失败: {e}")
                # 如果生成失败但有旧缓存，返回旧缓存
                if cached:
                    return cached.summary
                return ""