"""
桥接模块 — 所有导入已迁移到 app.domain.memory.vector_service。
保留此文件仅用于向后兼容。
"""
from app.domain.memory.vector_service import (  # noqa: F401
    VectorMemoryService,
    MemoryRetrievalRouter,
    ExternalAPIClient,
    _SHARED_EXECUTOR,
)
