"""
全局配置，使用 pydantic-settings 从 .env 加载。

使用 lru_cache 确保全局只有一个 Settings 实例，避免重复读取 .env。
所有模块统一通过 get_settings() 获取配置，禁止直接 Settings()。
"""
from functools import lru_cache

from pydantic_settings import BaseSettings
from typing import Literal


class Settings(BaseSettings):
    """应用配置，所有敏感信息从环境变量加载"""

    # ---------- 阿里百炼 (DashScope) 凭证 ----------
    DASHSCOPE_API_KEY: str
    DASHSCOPE_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    # ---------- DeepSeek (可选) ----------
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"

    # ---------- 模型选择 ----------
    LLM_MODEL: str = "deepseek-v4-pro"
    EMOTION_MODEL: str = "qwen3.7-plus"
    EMBED_MODEL: str = "text-embedding-v4"

    # ---------- 服务 ----------
    HOST: str = "127.0.0.1"
    PORT: int = 8000

    # ---------- 日志 ----------
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # ---------- 记忆模块 ----------
    CHROMA_PATH: str = "./chroma_data"
    COLLECTION_NAME: str = "companion_memories_v4"
    MEMORY_TOP_K: int = 5
    SIMILARITY_THRESHOLD: float = 0.15

    # ---------- 三层情感记忆向量化 ----------
    VECTOR_FACTS_COL: str = "memory_facts"
    VECTOR_EMOTIONS_COL: str = "memory_emotions"
    VECTOR_MILESTONES_COL: str = "memory_milestones"
    VECTOR_TOP_K_FACTS: int = 3
    VECTOR_TOP_K_EMOTIONS: int = 5
    VECTOR_TOP_K_MILESTONES: int = 3

    # ---------- 数据库 ----------
    DATABASE_URL: str = "postgresql+asyncpg://echosoul:123456@localhost:5432/echosoul?ssl=disable"
    REDIS_URL: str = "redis://localhost:6379/0"

    # ---------- 好感度系统 ----------
    AFFECTION_DB_PATH: str = "affection.db"
    AFFECTION_DECAY_PER_DAY: float = 2.0

    # ---------- 主动消息调度 ----------
    INACTIVE_HOURS: float = 2
    SCHEDULER_INTERVAL_MINUTES: int = 60

    # ---------- 认证 ----------
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    SECRET_KEY: str = "change-this-in-production"
    ALGORITHM: str = "HS256"

    # ---------- 嵌入维度 ----------
    EMBEDDING_DIM: int = 1536

    # ---------- WebSocket ----------
    USE_WEBSOCKET: bool = True
    WS_HEARTBEAT_INTERVAL: int = 30

    # ---------- 测试模式 ----------
    TEST_MODE: bool = False

    # ---------- Function Calling / 工具调用 ----------
    MAX_TOOL_ITERATIONS: int = 5
    TOOL_LLM_TEMPERATURE: float = 0.7
    TOOL_LLM_MAX_TOKENS: int = 1024

    # ---------- Skills ----------
    SKILLS_DIR: str = "./skills"
    ENABLE_SKILLS: bool = False

    # ---------- MCP ----------
    MCP_CONFIG_PATH: str = "./mcp_servers.json"
    ENABLE_MCP: bool = False

    model_config = {
        "env_file": ".env",
        "extra": "ignore",
    }


@lru_cache()
def get_settings() -> Settings:
    """返回全局唯一的 Settings 实例（lru_cache 确保只初始化一次）。"""
    return Settings()
