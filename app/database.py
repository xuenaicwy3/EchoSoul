"""
桥接模块 — 所有导入已迁移到 app.infrastructure.database。
保留此文件仅用于向后兼容。
"""
from app.infrastructure.database import (  # noqa: F401
    init_db,
    close_db,
    get_async_session,
    PARTITION_TABLES,
)
