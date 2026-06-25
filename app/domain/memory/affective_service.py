"""
桥接模块 — AffectiveMemoryService 待 Repository 注入改造。
当前直接从旧文件 re-export。
"""
from app.affective_memory_service import AffectiveMemoryService  # noqa: F401
