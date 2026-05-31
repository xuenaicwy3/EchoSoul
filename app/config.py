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
    EMOTION_MODEL: str = "qwen3.6-plus"              # 情感分析模型
    EMBED_MODEL: str = "text-embedding-v1"         # 向量嵌入模型

    # ---------- 服务 ----------
    HOST: str = "127.0.0.1"
    PORT: int = 9000

    # ---------- 日志 ----------
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # ---------- 记忆模块 ----------
    CHROMA_PATH: str = "./chroma_data"             # 向量数据库持久化路径
    COLLECTION_NAME: str = "companion_memories"    # 集合名称
    MEMORY_TOP_K: int = 5                          # 检索记忆数量
    SIMILARITY_THRESHOLD: float = 0.15             # 去重相似度阈值

    # ---------- 好感度系统 ----------
    AFFECTION_DB_PATH: str = "affection.db"        # SQLite 数据库路径
    AFFECTION_DECAY_PER_DAY: float = 2.0           # 每天衰减值

    # ---------- 主动消息调度 ----------
    INACTIVE_HOURS: int = 2                        # 连续未互动小时数后触发
    SCHEDULER_INTERVAL_MINUTES: int = 60           # 检查间隔（分钟）

    model_config = {
        "env_file": ".env",           # 指定从 .env 文件读取
        "extra": "ignore"             # 忽略未定义的额外字段
    }