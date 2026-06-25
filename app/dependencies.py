"""
桥接模块 — 所有导入已迁移到 app.api.deps。
保留此文件仅用于向后兼容。
"""
from app.api.deps import get_current_user, oauth2_scheme, auth_deps  # noqa: F401
