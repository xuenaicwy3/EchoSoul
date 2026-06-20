"""
全局配置，使用 pydantic-settings 从 .env 加载
所有配置项均通过类型注解获得自动验证和 IDE 提示
"""
from pydantic_settings import BaseSettings
from typing import Literal

class Settings(BaseSettings):
    """应用配置，所有敏感信息从环境变量加载"""
    # ---------- 阿里百炼 (DashScope) 凭证 ----------
    DASHSCOPE_API_KEY: str                         # API Key，必填
    DASHSCOPE_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    # ---------- 模型选择 ----------
    LLM_MODEL: str = "deepseek-v4-pro"             # 对话模型
    EMOTION_MODEL: str = "qwen3.7-plus"            # 情感分析模型
    EMBED_MODEL: str = "text-embedding-v4"         # 向量嵌入模型

    # ---------- 服务 ----------
    HOST: str = "127.0.0.1"
    PORT: int = 8000

    # ---------- 日志 ----------
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # ---------- 记忆模块 ----------
    CHROMA_PATH: str = "./chroma_data"             # 向量数据库持久化路径
    COLLECTION_NAME: str = "companion_memories_v4"    # 对话记忆集合名称
    MEMORY_TOP_K: int = 5                          # 检索记忆数量
    SIMILARITY_THRESHOLD: float = 0.15             # 去重相似度阈值

    # ---------- 三层情感记忆向量化 ----------
    VECTOR_FACTS_COL: str = "memory_facts"              # 事实层 Chroma 集合
    VECTOR_EMOTIONS_COL: str = "memory_emotions"         # 情感层 Chroma 集合
    VECTOR_MILESTONES_COL: str = "memory_milestones"     # 关系层 Chroma 集合
    VECTOR_TOP_K_FACTS: int = 3       # 事实层检索条数
    VECTOR_TOP_K_EMOTIONS: int = 5    # 情感层检索条数
    VECTOR_TOP_K_MILESTONES: int = 3  # 关系层检索条数

    # ---------- 数据库 ----------
    DATABASE_URL: str = "postgresql+asyncpg://echosoul:123456@localhost:5432//echosoul?ssl=disable"
    REDIS_URL: str = "redis://localhost:6379/0"

    # ---------- 好感度系统 ----------
    AFFECTION_DB_PATH: str = "affection.db"        # SQLite 数据库路径
    AFFECTION_DECAY_PER_DAY: float = 2.0           # 每天衰减值

    # ---------- 主动消息调度 ----------
    INACTIVE_HOURS: float= 2                      # 离线2小时后生成日志
    SCHEDULER_INTERVAL_MINUTES: int = 60               # 每60分钟扫描一次离线用户

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 单位：分钟（默认 24 小时）
    SECRET_KEY: str = "my-super-secret-key-change-this-in-production"
    ALGORITHM: str = "HS256"

    # ---------- 嵌入维度 ----------
    EMBEDDING_DIM: int = 1536  # 阿里云 text-embedding-v1 的向量维度

    USE_WEBSOCKET: bool = True  # 是否启用 WebSocket，默认开启
    WS_HEARTBEAT_INTERVAL: int = 30  # WebSocket 心跳间隔（秒）

    # ---------- 测试模式 ----------
    TEST_MODE: bool = False   # 设为 True 则跳过所有 AI 调用


    model_config = {
        "env_file": ".env",           # 指定从 .env 文件读取
        "extra": "ignore"             # 忽略未定义的额外字段
    }