"""
桥接模块 — 后处理逻辑已迁移到 app.workers.postprocess（EventBus 模式）。
保留此文件仅用于向后兼容。
"""
from app.workers.postprocess import process_postprocess_stream  # noqa: F401
