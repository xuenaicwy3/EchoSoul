"""
Celery 任务注册中心 — 类型安全的调用层。

每个 Celery 任务对应一个 Typed Wrapper 函数：
- Pydantic 模型做参数校验（编译期 + 运行时）
- IDE 可跳转到业务逻辑
- 调用方不感知 Celery 底层
"""
import logging
from typing import Optional

from pydantic import BaseModel, Field

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


# ==================== Payload 模型 ====================


class ChatTaskPayload(BaseModel):
    """process_chat 任务的参数模型。"""
    user_id: str
    role_type: Optional[str] = None
    user_input: str = ""
    preset_greeting: Optional[str] = None
    aff_info: str = "亲密度10, 信任10"
    unlock_info: str = ""
    thread_id: str
    need_regenerate: bool = False
    enable_tools: bool = False  # 是否启用工具调用
    active_skills: list = Field(default_factory=list)  # 预激活的技能名列表


# ==================== 类型安全的调用函数 ====================


def send_chat_task(payload: ChatTaskPayload) -> str:
    """
    发布聊天任务到 Celery Worker。

    IDE 可跳转到此函数 → 再跳转到 ChatTaskPayload → 再跳转到 process_chat 实现。
    参数错误在 Pydantic 校验阶段就会暴露，不会到运行时才炸。

    Returns:
        Celery task_id (UUID 字符串)
    """
    result = celery_app.send_task(
        "process_chat",
        args=[payload.model_dump()],
    )
    logger.info("[TaskRegistry] process_chat 已发布: task_id=%s", result.id)
    return result.id
