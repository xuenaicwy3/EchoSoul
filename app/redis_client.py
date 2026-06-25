"""
桥接模块 — 所有导入已迁移到 app.infrastructure.redis。
保留此文件仅用于向后兼容。
"""
from app.infrastructure.redis import (  # noqa: F401
    init_redis,
    close_redis,
    get_redis_client,
)
