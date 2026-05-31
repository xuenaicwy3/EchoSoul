"""
主动消息调度器
使用 APScheduler 异步调度，定期检查非活跃用户并生成主动消息
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from langchain.chat_models import init_chat_model
from app.config import Settings
from app.roles import RoleCatalog
from app.prompts import PromptFactory
from app.affection import AffectionService

logger = logging.getLogger(__name__)

class ProactiveScheduler:
    """主动消息调度器"""

    def __init__(self, settings: Settings, affection_service: AffectionService):
        self.settings = settings
        self.affection = affection_service
        self.llm = init_chat_model(
            model=settings.LLM_MODEL,
            model_provider="openai",
            api_key=settings.DASHSCOPE_API_KEY,
            base_url=settings.DASHSCOPE_BASE_URL,
            temperature=0.75
        )
        # 用户最后活跃时间（生产环境应改用 Redis）
        self.last_active: Dict[str, datetime] = {}
        # 待推送消息队列
        self.pending: Dict[str, List[str]] = {}
        self._scheduler = AsyncIOScheduler()
        logger.info("主动消息调度器已就绪")

    def update_active(self, user_id: str):
        """更新用户最后活跃时间"""
        self.last_active[user_id] = datetime.now()

    def get_pending(self, user_id: str) -> List[str]:
        """获取并清空用户的待推送消息"""
        return self.pending.pop(user_id, [])

    async def _check_and_generate(self):
        """定时任务：检查非活跃用户并生成主动消息"""
        threshold = datetime.now() - timedelta(hours=self.settings.INACTIVE_HOURS)
        for uid, last_time in list(self.last_active.items()):
            if last_time < threshold and uid not in self.pending:
                try:
                    # 默认使用温柔贤淑型，后续可改为从用户状态中获取
                    role_type = "温柔贤淑型"
                    role = RoleCatalog.get_role(role_type)
                    aff = self.affection.get(uid, role_type)
                    avg_aff = sum(aff.values()) / 4
                    prompt = PromptFactory.proactive_message(role, avg_aff)
                    msg = self.llm.invoke(prompt).content.strip()
                    self.pending[uid] = [msg]
                    logger.info("已为用户 %s 生成主动消息: %s", uid[:8], msg[:30])
                except Exception as e:
                    logger.error("生成主动消息失败: %s", e, exc_info=True)

        # 每日好感度衰减（凌晨3点左右）
        now = datetime.now()
        if now.hour == 3 and now.minute < 5:
            self.affection.apply_decay()

    def start(self):
        """启动定时任务"""
        self._scheduler.add_job(
            self._check_and_generate,
            trigger=IntervalTrigger(minutes=self.settings.SCHEDULER_INTERVAL_MINUTES),
            id='proactive_check',
            name='主动消息生成',
            replace_existing=True
        )
        self._scheduler.start()
        logger.info("调度器已启动，检查间隔=%d分钟", self.settings.SCHEDULER_INTERVAL_MINUTES)

    def shutdown(self):
        """关闭调度器"""
        self._scheduler.shutdown()
        logger.info("调度器已关闭")