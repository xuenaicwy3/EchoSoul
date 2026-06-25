"""
桥接模块 — MemoryRetrievalRouter 待从 vector_service 中抽取。
当前从旧文件 re-export。
"""
from app.vector_memory_service import MemoryRetrievalRouter  # noqa: F401
from app.domain.memory.vector_service import MemoryRetrievalRouter as _M  # noqa: F401
