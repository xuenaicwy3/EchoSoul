"""认证依赖"""
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from app.auth import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

async def get_current_user(token: str = Depends(oauth2_scheme)) -> str:
    user_id = decode_access_token(token)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证凭据",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user_id