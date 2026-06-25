"""
桥接模块 — 所有导入已迁移到 app.core.exceptions。
保留此文件仅用于向后兼容。
"""
from app.core.exceptions import (  # noqa: F401
    EchoSoulException,
    AuthenticationError,
    UserNotFoundError,
    DuplicateUserError,
    AIServiceError,
    EmotionAnalysisError,
    MemoryExtractionError,
    MemoryStoreError,
    MemoryRetrievalError,
    VectorSyncError,
    AffectionUpdateError,
    DatabaseNotInitializedError,
    RedisNotInitializedError,
)
