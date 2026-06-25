"""
桥接模块 — 所有导入已迁移到 app.core.config。
保留此文件仅用于向后兼容。
"""
from app.core.config import Settings, get_settings  # noqa: F401
