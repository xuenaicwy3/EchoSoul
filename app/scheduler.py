"""
桥接模块 — 所有导入已迁移到 app.workers.scheduler。
保留此文件仅用于向后兼容。
"""
from app.workers.scheduler import ProactiveScheduler  # noqa: F401
