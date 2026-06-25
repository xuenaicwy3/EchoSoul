"""
集中管理所有 FastAPI 依赖注入。

每个依赖在此文件中定义，路由通过 Depends 引用。
所有依赖链在此处集中可见，便于追踪和测试。
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.auth import decode_access_token
from app.core.config import get_settings, Settings

# ---- 认证 ----

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


async def get_current_user(token: str = Depends(oauth2_scheme)) -> str:
    """从 Bearer token 中解析当前用户 ID。"""
    user_id = decode_access_token(token)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证凭据",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user_id


# ---- 配置 ----

async def get_settings_dep() -> Settings:
    """获取全局 Settings 单例。"""
    return get_settings()


# ---- 认证依赖列表（路由复用） ----

auth_deps = [Depends(get_current_user)]
