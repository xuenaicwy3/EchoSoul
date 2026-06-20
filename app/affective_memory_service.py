import asyncio
import json
import logging
import math
from typing import List, Dict, Optional
from datetime import datetime, timezone, timedelta
from collections import Counter
from sqlalchemy import select, update, delete, func, desc
from app.database import get_async_session
from app.memoryDecayEngine import MemoryDecayEngine
from app.models.db_models import UserFact, EmotionRecord, RelationshipMilestone, UserMemorySummary

from app.config import Settings
from app.redis_client import get_redis_client
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

MAX_MEMORY_TEXT_LENGTH = 1200          # 结构化记忆文本最大长度
COMPRESSION_TARGET_LENGTH = 300        # LLM压缩目标长度

class AffectiveMemoryService:
    """
    三层情感记忆服务
    融合艾宾浩斯遗忘曲线、睡眠整理机制，支持记忆休眠与唤醒
    """
    def __init__(self, settings: Settings):
        self.settings = settings
        # 事实提取用轻量模型
        self.extract_llm = init_chat_model(
            model=settings.LLM_MODEL, model_provider="openai",
            temperature=0.1, max_tokens=200,
            api_key=settings.DASHSCOPE_API_KEY, base_url=settings.DASHSCOPE_BASE_URL
        )
        # 摘要生成/压缩用模型
        self.summary_llm = init_chat_model(
            model=settings.LLM_MODEL, model_provider="openai",
            temperature=0.2, max_tokens=300,
            api_key=settings.DASHSCOPE_API_KEY, base_url=settings.DASHSCOPE_BASE_URL
        )


    async def add_fact(self, user_id: str, role_type: str, key: str, value: str,
                       source: str = "extracted", salience: float = 0.5) -> bool:
        """
        新增或更新事实，自动计算半衰期和显著性。
        如果事实已存在则强化记忆（强度×1.2，半衰期延长），否则新建。
        :param user_id: 用户ID
        :param role_type: 角色类型
        :param key: 事实键
        :param value: 事实值
        :param source: 来源 (extracted/manual)
        :param salience: 显著性 0~1，越高越难遗忘
        :return: 是否成功
        """
        try:
            session = get_async_session()
        except RuntimeError:
            return False
        async with session() as s:
            result = await s.execute(
                select(UserFact).where(
                    UserFact.user_id == user_id, UserFact.role_type == role_type, UserFact.key == key
                )
            )
            fact = result.scalar_one_or_none()
            if fact:
                # 强化已有记忆
                fact.value = value
                fact.source = source
                fact.strength = min(1.0, fact.strength * 1.2)
                fact.last_reinforced = datetime.now(timezone.utc)
                fact.salience = max(fact.salience, salience)
                fact.half_life_days = max(fact.half_life_days,
                                          MemoryDecayEngine.get_half_life(fact.salience, source))
                fact.status = "active"
                logger.info(f"事实强化: {key}={value}")
            else:
                # 新建事实
                half_life = MemoryDecayEngine.get_half_life(salience, source)
                fact = UserFact(
                    user_id=user_id, role_type=role_type, key=key, value=value,
                    source=source, salience=salience, half_life_days=half_life,
                    strength=0.6, is_immutable=(salience >= 0.9), status="active"
                )
                s.add(fact)
                logger.info(f"事实新增: {key}={value}")
            await s.commit()
            return True

    async def get_facts(self, user_id: str, role_type: str) -> List[Dict]:
        """
        获取当前活跃且强度>0.15的事实。
        遗忘曲线计算实时强度，过滤已遗忘的记忆。
        :return: 事实列表 [{"key":..., "value":..., "source":..., "strength":...}]
        """
        try:
            session = get_async_session()
        except RuntimeError:
            return []
        async with session() as s:
            result = await s.execute(
                select(UserFact)
                .where(UserFact.user_id == user_id, UserFact.role_type == role_type, UserFact.status == "active")
                .order_by(UserFact.key)
            )
            facts = result.scalars().all()
            active = []
            now = datetime.now(timezone.utc)
            for f in facts:
                days_since = (now - f.last_reinforced).days
                current = MemoryDecayEngine.calculate_decayed_strength(f.strength, days_since, f.half_life_days)
                if current > 0.15:
                    active.append({
                        "key": f.key, "value": f.value, "source": f.source,
                        "strength": round(current, 2)
                    })
            return active

    async def reinforce_fact(self, user_id: str, role_type: str, key: str):
        """强化事实：冷却期内微增益，冷却期外间隔自适应强化"""
        try:
            session = get_async_session()
        except RuntimeError:
            return
        async with session() as s:
            result = await s.execute(
                select(UserFact).where(
                    UserFact.user_id == user_id,
                    UserFact.role_type == role_type,
                    UserFact.key == key
                )
            )
            fact = result.scalar_one_or_none()
            if not fact:
                return

            now = datetime.now(timezone.utc)
            # 统一计算分钟数，与 calculate_reinforcement 参数单位一致
            minutes_since = (now - fact.last_reinforced).total_seconds() / 60.0

            # 先计算当前衰减强度
            days_since = minutes_since / 1440.0
            current_strength = MemoryDecayEngine.calculate_decayed_strength(
                fact.strength, days_since, fact.half_life_days
            )

            # 调用统一的强化方法（内部根据冷却期自动选择微增益或完整强化）
            new_strength, new_half_life = MemoryDecayEngine.calculate_reinforcement(
                minutes_since, current_strength, fact.half_life_days
            )

            fact.strength = new_strength
            fact.half_life_days = new_half_life
            fact.last_reinforced = now
            await s.commit()
            logger.info(
                f"事实强化: {key}, 间隔 {days_since:.1f} 天, 强度 {new_strength:.2f}, 半衰期 {new_half_life} 天")

    # ==================== 事实层 ====================
    async def extract_facts_from_conversation(self, user_id: str, role_type: str,
                                              user_msg: str, ai_reply: str):
        """
        从对话中提取事实，自动判断显著性，支持强化活跃事实、唤醒归档记忆、新建事实。

        核心流程（三级记忆模型）：
        1. 先查找活跃（active）事实 → 若存在则强化（strength × 1.2，半衰期 +15%）
        2. 若未找到活跃事实，则查找归档（archived）记忆 → 若存在则唤醒（重置强度为0.4，半衰期为3天）
        3. 若均未找到，则新建事实（初始强度0.6，半衰期根据显著性计算）

        该方法通常在每次用户-AI交互后调用，用于持续更新用户画像。
        """
        try:
            session = get_async_session()  # 获取异步数据库会话工厂（可能依赖当前请求上下文）
        except RuntimeError:
            return                         # 若无法获取会话（如在非请求环境中），直接返回，避免崩溃
        try:
            # ---------- 1. 构造 LLM 提示词，提取结构化事实 ----------
            prompt = f"""分析下面的对话，提取关于用户的重要个人信息（如姓名、生日、喜好、讨厌的事物、职业、宠物等），
以 JSON 格式返回，key 为信息类型，value 为信息内容。同时为每个信息评估显著性分数（0-1）。
如果没有明确信息则返回空 JSON。只输出 JSON。

用户: {user_msg}
角色: {ai_reply}
JSON 格式示例: {{"喜好": {{"value": "动画", "salience": 0.8}}}}"""

            messages = [HumanMessage(content=prompt)]
            loop = asyncio.get_running_loop()

            # 将 LLM 调用放到线程池中执行，避免阻塞事件循环（因为 sync LLM 可能耗时）
            response = await loop.run_in_executor(None, self.extract_llm.invoke, messages)

            # ---------- 2. 解析 LLM 返回的 JSON ----------
            raw = response.content.strip()
            # 去除可能包含的 Markdown 代码块标记
            if raw.startswith("```json"): raw = raw[7:]
            if raw.endswith("```"): raw = raw[:-3]

            data = json.loads(raw)    # 解析为 Python 字典
            if not isinstance(data, dict):  # 若顶层不是字典（可能为空数组），则直接返回
                return

            # ---------- 3. 遍历每个提取出的事实，进行记忆处理 ----------
            async with session() as s:        # 创建数据库异步会话
                for key, val in data.items():
                    # 处理两种格式：{"key": {"value": "...", "salience": 0.8}} 或 直接 {"key": "..."}
                    if isinstance(val, dict) and 'value' in val:
                        value = str(val['value']).strip()
                        salience = float(val.get('salience', 0.5))
                    else:
                        value = str(val).strip()
                        salience = 0.5  # 默认显著性

                    if not value:       # 跳过空值
                        continue

                    # ---------- 3.1 查找活跃事实（status = 'active'） ----------
                    result = await s.execute(
                        select(UserFact).where(
                            UserFact.user_id == user_id, UserFact.role_type == role_type,
                            UserFact.key == key, UserFact.status == "active"
                        )
                    )
                    active_fact = result.scalar_one_or_none()
                    if active_fact:
                        # 调用统一的强化方法：强度 × 1.2，半衰期延长 15%（或增加固定天数）
                        await self.reinforce_fact(user_id, role_type, key)
                        # 同时更新值为最新提取的值（可能内容有变化）
                        active_fact.value = value
                        # 显著性取历史最大值（保留峰值）
                        active_fact.salience = max(active_fact.salience, salience)
                        continue   # 处理下一个 key

                    # ---------- 3.2 未找到活跃事实，尝试唤醒查找归档事实（status = 'archived'） ----------
                    result = await s.execute(
                        select(UserFact).where(
                            UserFact.user_id == user_id, UserFact.role_type == role_type,
                            UserFact.key == key, UserFact.status == "archived"
                        )
                    )
                    archived_fact = result.scalar_one_or_none()
                    if archived_fact:
                        # 唤醒归档记忆：将其状态改为 active，重置强度和半衰期（赋予较低的初始值）
                        archived_fact.status = "active"
                        archived_fact.value = value  # 可能更新为最新值
                        archived_fact.strength = MemoryDecayEngine.calculate_wake_up_strength() # 唤醒强度 0.4
                        archived_fact.half_life_days = MemoryDecayEngine.calculate_wake_up_half_life() # 唤醒记忆的半衰期
                        archived_fact.last_reinforced = datetime.now(timezone.utc)  # 记录唤醒时间
                        # 显著性仍取历史最大值
                        archived_fact.salience = max(archived_fact.salience, salience)
                        logger.info(f"事实唤醒: {key}={value}")
                        continue

                    # ---------- 3.3 既无活跃也无归档，则新建事实 ----------
                    # 调用 add_fact 方法，初始强度为 0.6（默认），半衰期根据 salience 计算，
                    # 来源标记为 "extracted"，状态为 "active"
                    await self.add_fact(user_id, role_type, key, value, "extracted", salience)

                # 循环结束后提交所有更改（包括强化、唤醒、新建）
                await s.commit()

        except Exception as e:
            logger.error(f"事实提取失败: {e}")

    # ==================== 情感层 ====================
    async def record_emotion(self, user_id: str, role_type: str,
                             label: str, score: float, message: Optional[str] = None):
        """
        记录一条情绪，并执行符合认知科学的情感记忆强化。

        科学基础:
        1. 情绪事件周期理论 (Russell, 2003): 一次情绪事件的生理和心理影响
           持续约10-20分钟。在此窗口内的重复识别属于同一情绪事件的维持，
           不应产生累积强化。因此设置15分钟冷却期。
        2. 情绪启动效应 (Bower, 1981): 当前情绪状态会增强对同类情绪信息的
           加工和提取。因此对24小时内同标签记录给予关联强化。
        3. 情绪记忆的消退理论 (LeDoux, 2000): 情绪记忆虽然持久，但若长期
           不被激活，其影响会逐渐减弱。通过半衰期14天实现自然衰减。
        4. 情绪多样性保护 (Fredrickson, 2001): 积极情绪的拓展-建构理论指出，
           情绪系统的健康在于多样性，不应让单一情绪完全主导。因此设置
           强度上限0.9后的微调机制。

        情绪记忆是用户短期情感状态的重要载体，具有时效性强、易波动、需快速响应的特点。
        本方法采用“新记录 + 即时强化近期同类 + 唤醒近期归档”三级策略，确保情感信息的动态更新。

        :param label: 情绪标签，如 "joy"（喜悦）、"sadness"（悲伤）、"anger"（愤怒）、"fear"（恐惧）等
        :param score: 情绪强度，范围 0~1，表示该情绪的强烈程度
        :param message: 可选的消息内容，用于记录触发该情绪的具体文本或上下文
        """
        try:
            session = get_async_session()     # 获取异步数据库会话工厂（与上层保持一致）
        except RuntimeError:
            return                            # 若无法获取会话，静默返回，避免影响主流程

        async with session() as s:            # 创建数据库异步会话（自动管理事务）
            # ---------- 1. 创建新情绪记录（初始为活跃状态） 记录当前情绪 ----------
            record = EmotionRecord(
                user_id=user_id, role_type=role_type,
                label=label, score=score, message=message,
                strength=1.0,       # 新情绪初始强度设为最高（1.0），表示刚产生时最鲜明
                half_life_days=14,  # 默认半衰期为14天，表示情绪若不强化，大约2周后强度减半
                status="active"     # 新记录直接设为活跃，参与后续衰减和检索
            )
            s.add(record)           # 添加到会话，暂未提交
            await s.commit()        # 先立即提交，确保记录持久化（后续更新可基于此ID）


            # ---------- 2. 关联强化24小时内同标签记录 ----------
            # 为什么是24小时？因为情绪具有短期集中性，例如用户连续表达“愤怒”时，这些记录应互相增强，
            # 以体现情绪的累积效应。
            # 调用独立的 reinforce_emotion 方法，使用情感层专属参数
            await self.reinforce_emotion(user_id, role_type, label)

            # ---------- 3. 唤醒7天内同标签的归档情绪记录 ----------
            # 为什么是7天？情绪通常在一周内具有较高的复发可能性。若用户之前有归档的同标签情绪，
            # 且最近（7天内）曾被强化过（说明刚被关注），则将其唤醒，避免新建重复记录。
            now = datetime.now(timezone.utc)
            week_ago = datetime.now(timezone.utc) - timedelta(days=7)
            result = await s.execute(
                select(EmotionRecord).where(
                    EmotionRecord.user_id == user_id,
                    EmotionRecord.role_type == role_type,
                    EmotionRecord.label == label,
                    EmotionRecord.status == "archived",         # 只查找已归档的记录
                    EmotionRecord.last_reinforced >= week_ago    # 且最后强化时间在7天内（表示近期仍有一定活跃度）
                )
            )
            for rec in result.scalars().all():
                # 唤醒操作：状态恢复为 active
                rec.status = "active"
                # 强度重置为0.3（低于新记录的1.0，也低于正常初始值0.6），表示“已经遗忘一部分，但仍有痕迹”
                rec.strength = 0.3
                # 半衰期设为7天，比新记录的14天短，表明唤醒后的记忆如果不进一步强化，会较快再次遗忘
                rec.half_life_days = 7
                # 更新最后强化时间为现在，作为新的衰减起点
                rec.last_reinforced = now
                logger.info(f"情绪记忆唤醒: {label}")

            # 提交所有变更（新记录、强化更新、唤醒更新）
            await s.commit()
            logger.info(f"情感记录: {label} ({score:.2f})")

    async def get_emotion_trend(self, user_id: str, role_type: str, limit: int = 30) -> Dict:
        """
        获取情绪趋势：对活跃记录进行时间加权，返回主导情绪和趋势。

        该方法从数据库中取出指定用户最近（默认30条）的活跃情绪记录，
        利用记忆衰减引擎计算每条记录的当前强度，以强度作为权重统计不同情绪的出现频次，
        从而得出当前主导情绪；同时通过比较近期（后5条）和更早期（前5条）的情绪分数
        来判断情绪趋势（上扬/低落/平稳）。

        :param user_id: 用户ID
        :param role_type: 角色类型（用于多角色场景）
        :param limit: 最多查询的记录条数（默认30条）
        :return: 包含 records（记录列表）、dominant_emotion（主导情绪标签）、
             trend（趋势字符串："上扬"/"低落"/"平稳"/"数据不足"）的字典
        """
        try:
            session = get_async_session()   # 获取异步会话工厂
        except RuntimeError:
            # 若无法获取会话，返回默认空状态，不影响主流程
            return {"records": [], "dominant_emotion": "neutral", "trend": "平稳"}
        async with session() as s:
            # ---------- 1. 查询最近活跃的情绪记录 ----------
            result = await s.execute(
                select(EmotionRecord)
                .where(EmotionRecord.user_id == user_id, EmotionRecord.role_type == role_type,
                       EmotionRecord.status == "active")  # 只关心活跃记录（未归档、未删除）
                .order_by(desc(EmotionRecord.created_at))     # 按创建时间降序（最新在前）
                .limit(limit)       # 只取最近 limit 条
            )
            # 反转顺序，使记录按时间从旧到新排列（方便后续比较趋势）
            records = list(reversed(result.scalars().all()))
            if not records:
                return {"records": [], "dominant_emotion": "neutral", "trend": "平稳"}

            # ---------- 2. 计算当前强度，构建加权标签列表 ----------
            now = datetime.now(timezone.utc)
            weighted_labels = []      # 用于统计情绪标签的加权列表
            for rec in records:
                # 计算距离最后强化/创建的天数
                days_since = (now - rec.last_reinforced).days
                # 利用记忆衰减引擎计算当前时刻该情绪记录的强度（考虑衰减）
                current_strength = MemoryDecayEngine.calculate_decayed_strength(rec.strength, days_since, rec.half_life_days)
                # 只保留强度大于0.1的记录（强度太低不足以影响主导情绪）
                if current_strength > 0.1:
                    # 将该情绪标签按强度比例重复添加，以模拟加权投票
                    # 强度×10 + 1 表示权重，例如强度0.5 → 6次，强度1.0 → 11次
                    # 这样在 Counter 统计时，高强度的情绪会获得更多票数
                    weighted_labels.extend([rec.label] * int(current_strength * 10 + 1))

            # 使用 Counter 统计标签出现次数，取出现最多的作为主导情绪
            # 如果 weighted_labels 为空，则默认为 "neutral"
            dominant = Counter(weighted_labels).most_common(1)[0][0] if weighted_labels else "neutral"

            # ---------- 3. 计算情绪趋势（上扬/低落/平稳） ----------
            # 只有记录数 >= 10 时才有足够数据判断趋势，否则提示“数据不足”
            if len(records) >= 10:
                # 取前5条（较早记录）和后5条（较近记录）的 score 平均值
                earlier_avg = sum(r.score for r in records[:5]) / 5
                later_avg = sum(r.score for r in records[-5:]) / 5
                # 后5条平均比前5条高 0.2 以上视为“上扬”，低 0.2 以上视为“低落”，否则“平稳”
                trend = "上扬" if later_avg > earlier_avg + 0.2 else ("低落" if later_avg < earlier_avg - 0.2 else "平稳")
            else:
                trend = "数据不足"

            # ---------- 4. 构造返回结果 ----------
            # 时间转为 ISO 格式字符串，便于序列化
            return {
                "records": [{"label": r.label, "score": r.score, "time": r.created_at.isoformat()} for r in records],
                "dominant_emotion": dominant,
                "trend": trend
            }


    async def add_milestone(self, user_id: str, role_type: str, event: str,
                            event_type: str, details: Optional[str] = None):
        """
        新增关系里程碑，初始强度1.0，半衰期60天。

        里程碑是关系层的重要节点，用于标记用户与角色之间关系发展的关键事件
        （如亲密度达到30/50/80）。新建的里程碑初始强度为最高值1.0，半衰期为60天，
        表示该事件在开始时记忆最为鲜明，之后缓慢衰减。60天的半衰期设计体现了
        里程碑的长期重要性——比一般事实（3~14天）和情绪（14天）要持久得多。

        :param user_id: 用户ID
        :param role_type: 角色类型
        :param event: 事件描述（如“亲密度达到50”），供展示用
        :param event_type: 事件类型（如“intimacy_50”），用于程序化识别
        :param details: 可选详细信息（如具体情境、对话上下文等）
        """
        try:
            session = get_async_session()
        except RuntimeError:
            return
        async with session() as s:
            # ---------- 创建里程碑记录对象 ----------
            milestone = RelationshipMilestone(
                user_id=user_id, role_type=role_type,
                event=event, # 人类可读的事件描述
                event_type=event_type, details=details,
                strength=1.0, half_life_days=60, status="active"
            )
            s.add(milestone)   # 添加到会话
            await s.commit()   # 提交事务，持久化到数据库
            logger.info(f"里程碑: {event}")

    async def get_milestones(self, user_id: str, role_type: str) -> List[Dict]:
        """
        获取活跃且强度>0.3的里程碑，最多5条。

        里程碑代表用户与角色之间关系发展的重要节点（如亲密度达到30/50/80）。
        该方法从数据库中获取所有状态为 active 的里程碑记录，然后利用记忆衰减引擎
        计算每条记录在当前时刻的实际强度（考虑时间衰减），只保留强度 > 0.3 的记录，
        并按创建时间降序排序后返回最多5条。

        :param user_id: 用户ID
        :param role_type: 角色类型
        :return: 里程碑列表，每个元素包含 event（事件描述）、event_type（事件类型）、
                 time（创建时间ISO格式），最多5条
        """
        try:
            session = get_async_session()
        except RuntimeError:
            return []    # 若无法获取会话，返回空列表
        async with session() as s:
            # ---------- 1. 查询所有活跃里程碑（status='active'） ----------
            # 注意：这里仅按创建时间降序排列，未直接按强度排序，因为强度需要动态计算
            result = await s.execute(
                select(RelationshipMilestone)
                .where(RelationshipMilestone.user_id == user_id, RelationshipMilestone.role_type == role_type,
                       RelationshipMilestone.status == "active")
                .order_by(desc(RelationshipMilestone.created_at))  # 最新创建的在前
            )
            milestones = result.scalars().all()

            # ---------- 2. 计算每条记录的当前强度，过滤出强度 > 0.3 的 ----------
            active = []           # 用于存放符合条件的里程碑
            now = datetime.now(timezone.utc)
            for m in milestones:
                # 计算距离最后强化/创建的天数
                days_since = (now - m.last_reinforced).days
                # 调用记忆衰减引擎计算当前强度（考虑指数衰减）
                current = MemoryDecayEngine.calculate_decayed_strength(m.strength, days_since, m.half_life_days)
                # 只保留强度大于0.3的里程碑（0.3表示仍有一定重要性，可被用户感知） # 事件描述（如“亲密度达到50”）
                if current > 0.3:
                    active.append({"event": m.event, "event_type": m.event_type, "time": m.created_at.isoformat()})

            # ---------- 3. 返回最多5条（已按创建时间降序排列，但注意上面遍历是按时间降序的） ----------
            # 由于遍历顺序是从新到旧，active列表也保持这个顺序，取前5个即为最新的且强度>0.3的里程碑
            return active[:5]

    async def reinforce_emotion(self, user_id: str, role_type: str, label: str):
        """
        强化24小时内同标签的情绪记录。
        强化情绪记录：冷却期内微增益，冷却期外执行完整间隔强化。
        与事实层的区别：
        - 冷却期更短（5分钟 vs 15分钟），因为情绪事件周期更短
        - 微增益幅度稍大（ε=0.01 vs 0.005），模拟情绪累积效应

        情感记忆与事实记忆的本质区别在于：情绪具有弥漫性和累积性。
        一次情绪事件的影响通常持续数分钟到数十分钟，在此期间的重复识别属于同一情绪事件的延续。
        因此，情感层的冷却期应该比事实层更短（5分钟 vs 15分钟），
        但微增益幅度应该稍大（ε=0.01 vs 0.005），以模拟情绪的“累积效应”。
        """
        try:
            session = get_async_session()
        except RuntimeError:
            return
        async with session() as s:
            # 查找24小时内同标签的活跃记录
            now = datetime.now(timezone.utc)
            yesterday = now - timedelta(hours=24)

            # 查询24小时内同标签的活跃记录（不包括刚刚新建的那条，避免重复强化）
            result = await s.execute(
                select(EmotionRecord).where(
                    EmotionRecord.user_id == user_id,
                    EmotionRecord.role_type == role_type,
                    EmotionRecord.label == label,
                    EmotionRecord.created_at >= yesterday,
                    EmotionRecord.status == "active"
                )
            )
            records = result.scalars().all()

            for rec in records:
                # 跳过刚刚创建的那条记录（它的 last_reinforced 就是当前时间，间隔为0）
                if rec.last_reinforced == now:
                    continue

                minutes_since = (now - rec.last_reinforced).total_seconds() / 60.0
                days_since = minutes_since / 1440.0

                # 先计算当前衰减后的强度
                current = MemoryDecayEngine.calculate_decayed_strength(
                    rec.strength, days_since, rec.half_life_days
                )

                # 调用统一的强化方法，冷却期=5分钟，epsilon=0.01（模拟情绪累积效应）
                new_strength, new_half_life = MemoryDecayEngine.calculate_reinforcement(
                    minutes_since, current, rec.half_life_days,
                    cooldown_minutes=5, epsilon=0.01
                )

                # 更新记录
                rec.strength = new_strength
                rec.half_life_days = new_half_life
                # 更新最后强化时间
                rec.last_reinforced = now
                logger.info(
                    f"情绪强化: {label}, 间隔 {minutes_since:.1f} 分钟, 强度 {rec.strength:.2f}"
                )

            await s.commit()


    async def reinforce_milestone(self, user_id: str, role_type: str, event_type: str):
        """
        强化里程碑：冷却期内微增益，冷却期外间隔自适应强化

        里程碑代表关系发展中的关键节点（如亲密度达到30/50/80），
        其强度会随时间衰减。当用户再次达到相同阈值或相关事件触发时，
        调用本方法增强该里程碑的记忆痕迹，使其更持久、更显著。

        :param user_id: 用户ID
        :param role_type: 角色类型
        :param event_type: 里程碑事件类型（如 "intimacy_30"、"intimacy_50"、"intimacy_80"）
        """
        try:
            session = get_async_session()
        except RuntimeError:
            return
        async with session() as s:
            result = await s.execute(
                select(RelationshipMilestone).where(
                    RelationshipMilestone.user_id == user_id,
                    RelationshipMilestone.role_type == role_type,
                    RelationshipMilestone.event_type == event_type
                )
            )
            milestone = result.scalar_one_or_none()
            if not milestone:
                return

            now = datetime.now(timezone.utc)
            # 统一使用分钟作为时间单位
            minutes_since = (now - milestone.last_reinforced).total_seconds() / 60.0

            # 先计算当前衰减强度（使用天数，与 calculate_decayed_strength 的单位一致）
            days_since = minutes_since / 1440.0
            current = MemoryDecayEngine.calculate_decayed_strength(
                milestone.strength, days_since, milestone.half_life_days
            )

            # 调用统一的强化方法（内部根据冷却期自动选择微增益或完整强化）
            new_strength, new_half_life = MemoryDecayEngine.calculate_reinforcement(
                minutes_since, current, milestone.half_life_days
            )

            milestone.strength = new_strength
            milestone.half_life_days = new_half_life
            milestone.last_reinforced = now
            await s.commit()
            logger.info(
                f"里程碑强化: {event_type}, 间隔 {days_since:.1f} 天, 强度 {new_strength:.2f}, 半衰期 {new_half_life} 天")

    # ==================== 关系层 ====================
    async def check_and_add_milestones(self, user_id: str, role_type: str, intimacy: float) -> bool:
        """
        根据亲密度自动添加里程碑（30/50/80），同时检查并唤醒对应的归档里程碑。

        里程碑是关系层的重要元素，标记用户与角色之间关系发展的关键节点（如亲密度达到特定数值）。
        本方法在每次亲密度更新后调用，负责：
        1. 检查当前亲密度是否达到预设阈值（30、50、80），若达到且尚未存在对应里程碑，则新建。
        2. 检查是否有相同事件类型的归档里程碑，若有且当前亲密度再次达到该阈值，则将其唤醒（恢复活跃）。

        :param user_id: 用户ID
        :param role_type: 角色类型
        :param intimacy: 当前亲密度数值（通常为0~100）
        :return: 是否添加了新里程碑（True/False）
        """
        # ---------- 1. 获取当前所有里程碑（只获取状态为 active 的？注意：get_milestones 方法可能默认只返回活跃的） ----------
        # 注意：此处假设 get_milestones 只返回 status='active' 的里程碑（需查看其实现）
        milestones = await self.get_milestones(user_id, role_type)
        # 构建已有里程碑的事件类型集合，用于去重
        existing = {m['event_type'] for m in milestones}
        added = False

        # ---------- 2. 检查亲密度阈值，若达到且不存在，则添加新里程碑 ----------
        # 亲密度 >= 30 且 没有 "intimacy_30" 里程碑
        if intimacy >= 30 and "intimacy_30" not in existing:
            await self.add_milestone(user_id, role_type, "亲密度达到30", "intimacy_30")
            added = True
        # 亲密度 >= 50 且 没有 "intimacy_50" 里程碑
        if intimacy >= 50 and "intimacy_50" not in existing:
            await self.add_milestone(user_id, role_type, "亲密度达到50", "intimacy_50")
            added = True
        # 亲密度 >= 80 且 没有 "intimacy_80" 里程碑
        if intimacy >= 80 and "intimacy_80" not in existing:
            await self.add_milestone(user_id, role_type, "亲密度达到80", "intimacy_80")
            added = True

        # ---------- 3. 唤醒归档的里程碑（若再次达到相同阈值） ----------
        # 例如：用户曾达到亲密度50并归档，后来亲密度下降又上升再次达到50，则应唤醒旧记录
        try:
            session = get_async_session()
        except RuntimeError:
            return added     # 若无法获取会话，静默返回，但新里程碑可能已添加
        async with session() as s:
            # 查询所有状态为 "archived" 且事件类型为三个阈值之一的里程碑
            result = await s.execute(
                select(RelationshipMilestone).where(
                    RelationshipMilestone.user_id == user_id,
                    RelationshipMilestone.role_type == role_type,
                    RelationshipMilestone.status == "archived",
                    RelationshipMilestone.event_type.in_(["intimacy_30", "intimacy_50", "intimacy_80"])
                )
            )
            # 遍历每个归档里程碑
            for m in result.scalars().all():
                # 从 event_type 中提取阈值数字（例如 "intimacy_50" -> 50）
                # 如果当前亲密度 >= 该阈值（表示再次达到），则唤醒该里程碑
                if intimacy >= int(m.event_type.split("_")[1]):
                    # 先调用统一的强化方法（可能更新强度、半衰期等，通常用于活跃记录）
                    await self.reinforce_milestone(user_id, role_type, m.event_type)
                    # 然后手动设置唤醒所需的字段（reforce_milestone 可能不改变 status，所以单独设置）
                    m.status = "active"      # 恢复为活跃状态
                    m.strength = 0.5         # 唤醒强度设为0.5（中等偏低）
                    m.half_life_days = 30    # 唤醒后半衰期为30天（比初始值可能更长，表现关系里程碑的持久性）
                    m.last_reinforced = datetime.now(timezone.utc)   # 更新最后强化时间
                    logger.info(f"里程碑唤醒: {m.event}")
            # 提交所有变更
            await s.commit()
        return added

    # ==================== 记忆摘要 ====================
    async def get_memory_summary(self, user_id: str, role_type: str) -> str:
        """
        获取或生成用户画像摘要。基于活跃记忆数量变化触发重生成（事实+3、情绪+10、里程碑+1、24小时刷新）。
        支持基于旧摘要迭代更新。

        记忆摘要是对用户当前状态的高度概括，用于AI角色快速理解用户背景。
        为了避免每次请求都重新生成（成本高、延迟大），本方法采用缓存机制，
        仅在满足特定条件时（数量变化超过阈值或超过24小时）才重新生成。

        :param user_id: 用户ID
        :param role_type: 角色类型
        :return: 用户画像摘要字符串，若生成失败则返回已有缓存或空字符串
        """
        try:
            session = get_async_session()
        except RuntimeError:
            return ""
        async with session() as s:
            # ---------- 1. 查询缓存的摘要（按更新时间降序取最新一条） ----------
            result = await s.execute(
                select(UserMemorySummary).where(
                    UserMemorySummary.user_id == user_id, UserMemorySummary.role_type == role_type
                ).order_by(desc(UserMemorySummary.updated_at)).limit(1)
            )
            cached = result.scalar_one_or_none()

            # ---------- 2. 统计当前各类活跃记录的数量 ----------
            # 统计活跃事实数量（status='active'）
            fact_count = (await s.execute(select(func.count()).select_from(UserFact).where(
                UserFact.user_id == user_id, UserFact.role_type == role_type, UserFact.status == "active"))).scalar() or 0

            # 统计活跃情绪记录数量
            emotion_count = (await s.execute(select(func.count()).select_from(EmotionRecord).where(
                EmotionRecord.user_id == user_id, EmotionRecord.role_type == role_type, EmotionRecord.status == "active"))).scalar() or 0

            # 统计活跃里程碑数量
            milestone_count = (await s.execute(select(func.count()).select_from(RelationshipMilestone).where(
                RelationshipMilestone.user_id == user_id, RelationshipMilestone.role_type == role_type, RelationshipMilestone.status == "active"))).scalar() or 0

            # ---------- 3. 判断是否需要重新生成摘要（触发条件） ----------
            need_regenerate = not cached   # 如果没有缓存，必须生成
            if cached:
                # 条件1：事实数量比缓存时增加超过3条
                if fact_count > (cached.fact_count or 0) + 3:
                    need_regenerate = True
                # 条件2：情绪数量比缓存时增加超过10条
                if emotion_count > (cached.emotion_count or 0) + 10:
                    need_regenerate = True
                # 条件3：里程碑数量有增加（只要有新增即触发，因为里程碑比较重要）
                if milestone_count > (cached.milestone_count or 0):
                    need_regenerate = True
                # 条件4：距离上次更新超过24小时（86400秒）
                if (datetime.now(timezone.utc) - cached.updated_at).total_seconds() > 86400:
                    need_regenerate = True

            # 如果不需要重新生成且有缓存，直接返回缓存的摘要
            if not need_regenerate and cached:
                return cached.summary

            # ---------- 4. 需要重新生成：获取当前活跃记忆数据 ----------
            # 获取活跃事实（通过已有的 get_facts 方法）
            facts = await self.get_facts(user_id, role_type)
            # 获取情绪趋势（最近10条）
            trend = await self.get_emotion_trend(user_id, role_type, limit=10)
            # 获取活跃且强度>0.3的里程碑
            milestones = await self.get_milestones(user_id, role_type)

            # 格式化文本供LLM使用
            fact_text = "\n".join([f"- {f['key']}: {f['value']}" for f in facts]) if facts else "暂无"
            emotion_text = f"主导情绪: {trend['dominant_emotion']}，趋势: {trend['trend']}" if trend['records'] else "暂无"
            milestone_text = "\n".join([f"- {m['event']} ({m['time'][:10]})" for m in milestones[:5]]) if milestones else "暂无"

            # ---------- 5. 构造 LLM 提示词 ----------
            # 如果有旧摘要，采用迭代更新模式（保留历史重要信息，融入新变化）
            if cached and cached.summary:
                prompt = f"""你是一位用户画像维护助手。下面是一份已有的用户画像摘要，以及最近发生的新信息。请基于这些内容更新画像摘要，确保保留重要历史信息，同时融入新变化。输出不超过200字。

已有画像：
{cached.summary}

最新资料：
- 事实：{fact_text}
- 近期情绪：{emotion_text}
- 重要事件：{milestone_text}

请输出更新后的用户画像摘要（不要编号，直接叙述）："""
            else:
                prompt = f"""请根据下面的用户信息，生成一段简短的用户画像摘要（不超过200字），用于AI角色与用户的对话上下文中。

用户基本资料：
{fact_text}

用户近期情绪状态：
{emotion_text}

重要关系事件：
{milestone_text}

请用流畅的自然语言概括，不要编号，直接输出摘要内容。"""

            # ---------- 6. 调用 LLM 生成或更新摘要 ----------
            try:
                messages = [HumanMessage(content=prompt)]
                loop = asyncio.get_running_loop()
                # 将 LLM 调用放到线程池执行，避免阻塞事件循环
                response = await loop.run_in_executor(None, self.summary_llm.invoke, messages)
                new_summary = response.content.strip()

                # 更新或新增缓存记录
                if cached:
                    # 更新已有缓存
                    cached.summary = new_summary
                    cached.emotion_count = emotion_count
                    cached.fact_count = fact_count
                    cached.milestone_count = milestone_count
                    cached.updated_at = datetime.now(timezone.utc)
                else:
                    # 新建缓存记录
                    cached = UserMemorySummary(
                        user_id=user_id, role_type=role_type,
                        summary=new_summary, emotion_count=emotion_count,
                        fact_count=fact_count, milestone_count=milestone_count
                    )
                    s.add(cached)
                await s.commit()  # 提交事务
                logger.info(f"记忆摘要已{'更新' if cached else '生成'}，长度={len(new_summary)}")
                return new_summary
            except Exception as e:
                logger.error(f"摘要生成失败: {e}")
                return cached.summary if cached else ""

    # ==================== 结构化记忆缓存 ====================
    async def cache_structured_memory(self, user_id: str, role_type: str,
                                      facts=None, trend=None, milestones=None, summary=None):
        """
        构建结构化记忆文本并缓存到Redis。

        该方法负责将用户的各种记忆数据（事实、情绪趋势、里程碑、摘要）整合成一段
        结构化的自然语言文本，并存储到 Redis 缓存中，供 AI 角色在对话时快速获取
        用户背景信息。为了控制上下文长度，采用了**三阶段渐进式压缩**策略：

        1. **紧凑格式**：去除冗余描述，改用简洁的列举格式（如 "姓名:张三"）。
        2. **显著性过滤**：只保留显著性（salience ≥ 0.7）或强度（strength > 0.8）较高的事实。
        3. **LLM 压缩**：调用大语言模型对过滤后的文本进行摘要式压缩，并验证关键事实是否保留。

        如果原始文本长度已经符合限制，则直接缓存，跳过后续压缩阶段。

        :param user_id: 用户ID
        :param role_type: 角色类型
        :param facts: 事实列表（可选，若不传则自动获取）
        :param trend: 情绪趋势字典（可选，若不传则自动获取）
        :param milestones: 里程碑列表（可选，若不传则自动获取）
        :param summary: 已有摘要（可选，若不传则自动获取）
        """
        # ---------- 1. 获取数据（若未提供则从数据库获取） ----------
        if facts is None:
            facts = await self.get_facts(user_id, role_type)
        if trend is None:
            trend = await self.get_emotion_trend(user_id, role_type, limit=5)
        if milestones is None:
            milestones = await self.get_milestones(user_id, role_type)
        if summary is None:
            summary = await self.get_memory_summary(user_id, role_type)

        # ---------- 2. 构建原始文本（使用辅助方法） ----------
        raw = self._build_raw_text(facts, trend, milestones, summary)
        # 如果原始文本长度已经小于等于最大限制（例如 1200 字符），直接缓存并返回
        if len(raw) <= MAX_MEMORY_TEXT_LENGTH:
            await self._set_cache(user_id, role_type, raw)
            return

        # ---------- 阶段一：紧凑格式 ----------
        # 将原始文本转换为更紧凑的表示（例如去除不必要的修饰词，使用短句）
        compact = self._compact_format(raw)
        if len(compact) <= MAX_MEMORY_TEXT_LENGTH:
            await self._set_cache(user_id, role_type, compact)
            return

        # ---------- 阶段二：显著性过滤 ----------
        # 只保留高显著性（≥0.7）或高强度（>0.8）的事实
        important_facts = [f for f in facts if f.get('salience', 0) >= 0.7 or f.get('strength', 0) > 0.8]
        # 若没有符合条件的事实，则退而求其次，按强度排序取强度最高的 1 条（至少保留一点信息）
        if not important_facts:
            important_facts = sorted(facts, key=lambda f: f.get('strength', 0), reverse=True)[:1]
        # 用筛选后的事实重新构建文本（情绪和里程碑保持不变）
        filtered_text = self._build_raw_text(important_facts, trend, milestones, summary)
        if len(filtered_text) <= MAX_MEMORY_TEXT_LENGTH:
            await self._set_cache(user_id, role_type, filtered_text)
            return

        # ---------- 阶段三：LLM 压缩 ----------
        # 调用大语言模型对过滤后的文本进行智能摘要，进一步压缩长度
        try:
            compressed = await self._llm_compress(filtered_text)
            # 验证压缩后的文本是否保留了原始事实的关键键值（防止 LLM 丢失核心信息）
            original_keys = {f['key'] for f in facts}
            if self._validate_fact_keys(original_keys, compressed):
                # 验证通过，缓存压缩后的文本
                await self._set_cache(user_id, role_type, compressed)
            else:
                # 若验证失败（关键事实丢失），则直接截断过滤文本到最大长度并缓存（降级方案）
                await self._set_cache(user_id, role_type, filtered_text[:MAX_MEMORY_TEXT_LENGTH])
        except Exception as e:
            logger.error(f"LLM压缩失败: {e}")
            # LLM 调用异常时，同样截断过滤文本并缓存
            await self._set_cache(user_id, role_type, filtered_text[:MAX_MEMORY_TEXT_LENGTH])

    def _build_raw_text(self, facts, trend, milestones, summary) -> str:
        """
        将各类记忆数据构建成结构化的原始文本（供缓存或进一步压缩使用）。

        本方法是 `cache_structured_memory` 的核心辅助方法，负责将四种不同类型的
        记忆数据（事实、情绪趋势、里程碑、摘要）按照固定的格式组织成易于阅读和
        LLM 处理的自然语言文本。各部分通过换行符分隔，便于后续分段处理或截断。

        :param facts: 事实列表，每个元素应包含 'key' 和 'value' 字段（可能还有 'salience'、'strength'）
        :param trend: 情绪趋势字典，包含 'records'（记录列表）、'dominant_emotion'（主导情绪）、
                      'trend'（趋势字符串，如 "上扬"/"低落"/"平稳"）
        :param milestones: 里程碑列表，每个元素应包含 'event' 和 'time' 字段（可选）
        :param summary: 用户画像摘要字符串（通常由 LLM 生成）
        :return: 拼接好的结构化文本字符串，各部分按顺序用换行分隔
        """
        parts = []  # 存储各部分的文本片段

        # ---------- 1. 事实部分 ----------
        if facts:
            # 将每个事实格式化为 "- key: value" 的形式，并换行连接
            parts.append("关于用户的已知信息：\n" + "\n".join([f"- {f['key']}: {f['value']}" for f in facts]))

        # ---------- 2. 情绪趋势部分 ----------
        if trend and trend.get('records'):
            # 取最近 3 条情绪记录，格式化为 "标签(分数)"，并用逗号连接
            recent = ", ".join([f"{r['label']}({r['score']:.1f})" for r in trend['records'][-3:]])
            # 拼接主导情绪和趋势（若 trend 中没有 'trend' 字段，默认为 "平稳"）
            parts.append(f"用户最近情绪: {recent}，主导情绪: {trend['dominant_emotion']}，趋势: {trend.get('trend', '平稳')}")

        # ---------- 3. 里程碑部分 ----------
        if milestones:
            # 取前 3 个里程碑（通常按重要性或时间排序），格式化为 "- event (日期)"，
            # 其中日期只取前10个字符（通常是 YYYY-MM-DD）
            parts.append("重要事件：\n" + "\n".join([f"- {m['event']} ({m.get('time', '')[:10]})" for m in milestones[:3]]))

        # ---------- 4. 摘要部分 ----------
        if summary:
            # 用特殊标记标识摘要内容，便于 LLM 区分
            parts.append(f"【用户画像摘要】{summary}")

        # 用换行符将所有部分连接成一个完整的文本
        return "\n".join(parts)

    def _compact_format(self, text: str) -> str:
        """
        紧凑格式：将事实列表合并为一行 key=value; 形式。

        该方法是 cache_structured_memory 中三阶段压缩的第一阶段。
        它的目标是将原始结构化文本中的事实列表（以 "- key: value" 形式逐行列出）
        压缩为更紧凑的 "key=value; key2=value2; ..." 单行格式，
        从而减少换行符和冗余字符，缩短文本长度。

        :param text: 原始结构化文本（由 _build_raw_text 生成）
        :return: 压缩后的文本
        """
        # 按行分割原始文本
        lines = text.split("\n")
        new_lines = []             # 存储处理后的行
        facts_started = False       # 标记是否正在处理事实列表区域

        # 逐行遍历
        for line in lines:
            # 检测到事实列表的标题行："关于用户的已知信息："
            if line.startswith("关于用户的已知信息："):
                # 保留标题，但改为更简洁的 "用户信息: "
                new_lines.append("用户信息: ")
                facts_started = True   # 进入事实列表区域

            # 在事实列表区域内，且当前行以 "- " 开头（表示一个事实条目）
            elif facts_started and line.startswith("- "):
                # 去除开头的 "- "，并将 ": " 替换为 "="，得到 "key=value" 格式
                compact = line[2:].replace(": ", "=", 1)  # 只替换第一个冒号，避免value中的冒号被误改
                # 如果上一行末尾是 ": "（即标题行），直接追加紧凑内容
                if new_lines[-1].endswith(": "):
                    new_lines[-1] += compact
                else:
                    # 否则先加分号分隔，再追加
                    new_lines[-1] += compact + "; "

            # 非事实列表区域的其他行（如情绪、里程碑、摘要等）
            else:
                # 追加当前行，并重置 facts_started 标记（离开事实列表区域）
                new_lines.append(line)
                facts_started = False

        # 将处理后的行重新用换行符连接
        return "\n".join(new_lines)

    async def _llm_compress(self, text: str) -> str:
        """轻量LLM压缩，强制保留所有事实键，目标300字以内"""
        prompt = f"""你是一个精确的信息压缩助手。请将下面这段用户记忆文本压缩到 {COMPRESSION_TARGET_LENGTH} 字以内，同时必须满足以下要求：
1. 所有事实键值对必须完整保留，格式如 "[喜好=动画; 学战都市] [生日=5月20日]"
2. 情绪趋势必须保留，格式如 "近期情绪: joy(0.9), sadness(0.3); 主导: joy; 趋势: 平稳"
3. 里程碑保留最重要的2个，用分号分隔
4. 如果输入文本已经足够简短，直接返回原文，不要修改
5. 直接输出压缩后的文本，不要添加任何解释、前缀或后缀。

原始文本：
{text}"""
        messages = [HumanMessage(content=prompt)]
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, self.summary_llm.invoke, messages)
        return response.content.strip()

    def _validate_fact_keys(self, original_keys: set, compressed_text: str) -> bool:
        """校验所有原始事实键是否都出现在压缩文本中"""
        for key in original_keys:
            if key not in compressed_text:
                return False
        return True

    async def _set_cache(self, user_id: str, role_type: str, text: str):
        """将结构化记忆写入Redis，有效期3600秒"""
        r = get_redis_client()
        await r.setex(f"structured_memory:{user_id}:{role_type}", 3600, text)
        logger.info(f"结构化记忆已缓存 (长度={len(text)})")

    # ==================== 睡眠整理 ====================
    async def memory_consolidation(self, user_id: str, role_type: str):
        """执行三层记忆的睡眠整理：修剪事实、聚合情绪、压缩里程碑"""
        await self._prune_weak_facts(user_id, role_type)
        await self._compact_emotions(user_id, role_type)
        await self._compact_milestones(user_id, role_type)

    async def _prune_weak_facts(self, user_id: str, role_type: str):
        """
        事实层修剪：归档休眠记忆，删除垃圾记忆。

        科学模拟：大脑在睡眠中进行的突触修剪——清除无用连接（删除），
        保留潜在有用的连接（归档休眠）。

        该方法定期（或按需）清理用户事实层中已经变得很弱或完全无用的记录。
        它遍历所有状态为 'active' 的事实，利用记忆衰减引擎计算当前强度，
        然后根据以下策略处理：
        1. 若强度极低且置信度低且非硬约束 → 物理删除（垃圾回收）
        2. 若强度中等偏低但有一定显著性 → 归档（转为 archived 状态，保留但不活跃）

        注意：当前实现可能调用了 MemoryDecayEngine.should_archive_fact，
        但该类中未显式定义该方法，可能是一个内部辅助方法或命名不一致。
        实际归档条件可能参考 `should_archive_fact` 方法（强度在 [0.05, 0.15) 且 salience >= 0.4）。

        :param user_id: 用户ID
        :param role_type: 角色类型
        """
        try:
            session = get_async_session()
        except RuntimeError:
            return
        async with session() as s:
            now = datetime.now(timezone.utc)

            # ---------- 1. 查询所有活跃的事实记录 ----------
            result = await s.execute(
                select(UserFact).where(
                    UserFact.user_id == user_id,
                    UserFact.role_type == role_type,
                    UserFact.status == "active"
                )
            )
            facts = result.scalars().all()

            # ---------- 2. 遍历每条事实，评估当前强度并决定处理方式 ----------
            for fact in facts:
                # 计算距离最后强化的天数
                days_since = (now - fact.last_reinforced).days
                # 根据衰减引擎计算当前强度（考虑半衰期）
                current_strength = MemoryDecayEngine.calculate_decayed_strength(
                    fact.strength, days_since, fact.half_life_days)

                # ---------- 2.1 判断是否应该物理删除（垃圾事实） ----------
                # 删除条件：强度 < 0.05（极弱）且显著性 < 0.4（不重要）且超过30天（已过一个月）且非硬约束。
                if MemoryDecayEngine.should_prune_fact(
                        current_strength,
                        fact.salience,
                        days_since,
                        fact.is_immutable
                ):
                    await s.delete(fact)
                    logger.info(f"垃圾事实已删除: {fact.key}")

                # ---------- 2.2 若未删除，判断是否应归档（休眠记忆） ----------
                # 归档条件通常为：强度虽低但有一定重要性，保留以备将来唤醒
                # 条件：强度在 [0.05, 0.15) 之间（中等偏低）且显著性 >= 0.4（有一定重要性）。
                elif MemoryDecayEngine.should_archive_fact(current_strength, fact.salience):
                    fact.status = "archived"        # 状态改为归档，不再参与活跃查询
                    logger.info(f"事实已归档: {fact.key}")

            # 提交所有变更（删除和更新）
            await s.commit()

    async def _compact_emotions(self, user_id: str, role_type: str):
        """
        认知级情感层聚合：模拟海马体的模式分离与修剪功能。
        它不再简单地删除旧数据，而是基于情绪模式的持续性和显著性进行决策。
        """
        try:
            session = get_async_session()
        except RuntimeError:
            return
        async with session() as s:
            # ---------- 1. 筛选出最后强化时间超过90天的活跃情绪记录 ----------
            # 90天（约一个季度）是情感记忆的“保质期”阈值，超过此期限且未强化的情绪
            # 被认为已经“过期”，需要进行清理或归档。
            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(days=90)

            result = await s.execute(
                select(EmotionRecord).where(
                    EmotionRecord.user_id == user_id,
                    EmotionRecord.role_type == role_type,
                    EmotionRecord.last_reinforced < cutoff,
                    EmotionRecord.status == "active"
                )
            )

            # ---------- 2. 遍历每条过期情绪记录 ----------
            for rec in result.scalars().all():
                # 计算距离最后强化的天数
                days_since = (datetime.now(timezone.utc) - rec.last_reinforced).days
                # 计算当前强度（考虑衰减）
                current_strength = MemoryDecayEngine.calculate_decayed_strength(
                    rec.strength, days_since, rec.half_life_days
                )

                # ---------- 2.1 统计该情绪标签的历史出现次数（包括活跃和归档） ----------
                # 这个计数用于判断该情绪是否为用户的长期情绪模式（持续出现多次），
                # 还是仅有一次性的情绪波动。
                count = await s.scalar(
                    select(func.count()).where(
                        EmotionRecord.user_id == user_id,
                        EmotionRecord.role_type == role_type,
                        EmotionRecord.label == rec.label,
                        EmotionRecord.status.in_(["active", "archived"])  # 包含已归档的记录
                    )
                )

                # ---------- 2.2 判断是否应该物理删除 ----------
                # should_prune_emotion 条件：强度 < 0.03 且 超过90天 且 连续性计数 < 3
                # 这意味着：极低强度、过期、且不是持续出现的情绪，视为一次性情绪，可以直接删除
                if MemoryDecayEngine.should_prune_emotion(current_strength, days_since, count):
                    await s.delete(rec)
                    logger.info(f"一次性情绪已修剪: {rec.label}")

                # ---------- 2.3 若未删除，判断是否应归档 ----------
                # should_archive_emotion 条件：强度 < 0.03 且 超过90天
                # 归档意味着保留记录但不再参与活跃查询，以备将来可能唤醒
                elif MemoryDecayEngine.should_archive_emotion(current_strength, days_since):
                    rec.status = "archived"
                    logger.info(f"陈旧情绪已归档: {rec.label}")

            await s.commit()

    async def _compact_milestones(self, user_id: str, role_type: str):
        """
        认知级关系层压缩：模拟大脑对早期记忆的模糊化与遗忘。

        处理逻辑（按优先级）：
        1. 压缩 (compress)：调用 should_compress_milestone 判断，满足则删除并合并为摘要。
           适用于强度极弱(<0.1)且超一年(>365天)的里程碑，无论当前是 active 还是 archived。
        2. 归档 (archive)：调用 should_archive_milestone 判断，满足但未达压缩阈值时，
           将 active 记录转为 archived。适用于强度较低(<0.15)且超半年(>180天)的记录。
        3. 已存在的摘要里程碑同样接受两阶段判断，实现二次遗忘。
        """
        try:
            session = get_async_session()
        except RuntimeError:
            return
        async with session() as s:
            now = datetime.now(timezone.utc)

            # 1. 拉取该用户-角色下所有里程碑（active + archived），在应用层逐条判断
            result = await s.execute(
                select(RelationshipMilestone).where(
                    RelationshipMilestone.user_id == user_id,
                    RelationshipMilestone.role_type == role_type
                )
            )
            all_milestones = result.scalars().all()

            to_archive: list[RelationshipMilestone] = []
            to_compress: list[RelationshipMilestone] = []

            for m in all_milestones:
                days_since = (now - m.last_reinforced).total_seconds() / 86400.0

                # 条件：强度 < 0.1（极弱）且超过365天（一年） 压缩
                if MemoryDecayEngine.should_compress_milestone(m.strength, days_since):
                    to_compress.append(m)
                # 条件：强度 < 0.15（较低）且超过180天 归档
                elif MemoryDecayEngine.should_archive_milestone(m.strength, days_since):
                    if m.status == "active":
                        to_archive.append(m)

            # 2. 归档：将满足归档条件但未达压缩阈值的 active 记录转为 archived
            if to_archive:
                for m in to_archive:
                    m.status = "archived"
                logger.info(f"归档了{len(to_archive)}条里程碑。")

            # 3. 压缩：删除满足压缩条件的记录并生成摘要
            if to_compress:
                summary_text = "；".join([m.event for m in to_compress])
                for m in to_compress:
                    await s.delete(m)

                s.add(RelationshipMilestone(
                    user_id=user_id, role_type=role_type,
                    event=f"早期里程碑: {summary_text}",
                    event_type="summary",
                    strength=0.3, half_life_days=60, status="active"
                ))
                logger.info(f"压缩并生成了新的摘要里程碑，共{len(to_compress)}条。")

            await s.commit()