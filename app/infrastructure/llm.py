"""
LLM 客户端统一工厂。

所有 LLM 实例通过此模块创建，确保一致的 provider、base_url、api_key。
避免各 Service 各自 init_chat_model 导致的配置散落。
"""
from typing import Optional

from langchain.chat_models import init_chat_model

from app.core.config import get_settings


def create_chat_model(
    temperature: float = 0.8,
    max_tokens: int = 512,
    model: Optional[str] = None,
) -> "BaseChatModel":
    """创建对话 LLM 实例。

    Args:
        temperature: 温度参数（0-2），越高越随机。
        max_tokens: 最大输出 token 数。
        model: 模型名称，默认使用 Settings.LLM_MODEL。
    """
    settings = get_settings()
    return init_chat_model(
        model=model or settings.LLM_MODEL,
        model_provider="openai",
        temperature=temperature,
        max_tokens=max_tokens,
        api_key=settings.DASHSCOPE_API_KEY,
        base_url=settings.DASHSCOPE_BASE_URL,
    )


def create_extract_model() -> "BaseChatModel":
    """创建事实提取用 LLM（低温度、低 token）。"""
    return create_chat_model(temperature=0.1, max_tokens=200)


def create_summary_model() -> "BaseChatModel":
    """创建摘要生成用 LLM（中等温度、中等 token）。"""
    return create_chat_model(temperature=0.2, max_tokens=300)


def create_router_model() -> "BaseChatModel":
    """创建路由决策用 LLM（零温度、最小 token）。"""
    return create_chat_model(temperature=0.0, max_tokens=30)


def create_proactive_model() -> "BaseChatModel":
    """创建主动消息生成用 LLM（高温度、默认 token）。"""
    return create_chat_model(temperature=0.75)
