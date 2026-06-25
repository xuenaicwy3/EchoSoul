"""
桥接模块 — 所有导入已迁移到 app.domain.roles.catalog。
保留此文件仅用于向后兼容。
"""
from app.domain.roles.catalog import Role, RoleCatalog  # noqa: F401
