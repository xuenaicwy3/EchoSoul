"""
Harness Model 层 —— 低频迭代，改模型不动 Harness。

职责：封装 LLM 模型创建，Harness 层通过此接口获取模型实例。
换模型只需改 .env 配置，不影响 Harness 代码。
"""
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from app.core.config import get_settings


@dataclass
class ModelConfig:
    """模型配置 — 换模型只需改此类字段或 .env。"""
    chat_model: str = ""
    emotion_model: str = ""
    embed_model: str = ""
    temperature: float = 0.8
    max_tokens: int = 512
    tool_temperature: float = 0.7
    tool_max_tokens: int = 1024

    def __post_init__(self):
        settings = get_settings()
        if not self.chat_model:
            self.chat_model = settings.LLM_MODEL
        if not self.emotion_model:
            self.emotion_model = settings.EMOTION_MODEL
        if not self.embed_model:
            self.embed_model = settings.EMBED_MODEL


class ModelProvider:
    """Model 层 — Harness 获取 LLM 的唯一入口。

    用法:
      provider = ModelProvider(ModelConfig())
      chat_llm = provider.get_chat_llm()
      tool_llm = provider.get_tool_llm()
    """

    def __init__(self, config: Optional[ModelConfig] = None):
        self.config = config or ModelConfig()
        self.settings = get_settings()

    # ---- 对话模型 ----

    def get_chat_llm(self) -> BaseChatModel:
        """基础对话 LLM（generate_node 用）。"""
        return init_chat_model(
            model=self.config.chat_model,
            model_provider="openai",
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            api_key=self.settings.DASHSCOPE_API_KEY,
            base_url=self.settings.DASHSCOPE_BASE_URL,
        )

    def get_tool_llm(self) -> BaseChatModel:
        """工具调用 LLM（router_node 用，支持 bind_tools）。"""
        return init_chat_model(
            model=self.config.chat_model,
            model_provider="openai",
            temperature=self.config.tool_temperature,
            max_tokens=self.config.tool_max_tokens,
            api_key=self.settings.DASHSCOPE_API_KEY,
            base_url=self.settings.DASHSCOPE_BASE_URL,
        )

    # ---- 情绪模型 ----

    def get_emotion_llm(self):
        """情绪分析 LLM（EmotionService 用）。"""
        return init_chat_model(
            model=self.config.emotion_model,
            model_provider="openai",
            temperature=0.1,
            max_tokens=300,
            api_key=self.settings.DASHSCOPE_API_KEY,
            base_url=self.settings.DASHSCOPE_BASE_URL,
        )

    # ---- 嵌入模型 ----

    def get_embedding_model(self):
        """文本嵌入模型。"""
        from langchain_community.embeddings import DashScopeEmbeddings
        return DashScopeEmbeddings(
            model=self.config.embed_model,
            dashscope_api_key=self.settings.DASHSCOPE_API_KEY,
        )
