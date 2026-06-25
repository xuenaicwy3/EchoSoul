"""
桥接模块 — 所有导入已迁移到 app.game_service。
待 GameService 重构后移除此桥接。
"""
from app.game_service import GameService  # noqa: F401
