"""
桥接模块 — 所有导入已迁移到 app.domain.tts.service。
保留此文件仅用于向后兼容。
"""
from app.domain.tts.service import TTSService  # noqa: F401
