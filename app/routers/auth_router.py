import logging
from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from app.models.user import User
from app.database import get_async_session
from app.auth import get_password_hash, verify_password, create_access_token
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

class UserRegister(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6, max_length=128)

class UserLogin(BaseModel):
    username: str
    password: str

@router.post("/register")
async def register(user_data: UserRegister):
    try:
        async_session = get_async_session()
        if async_session is None:
            logger.error("async_session 未初始化")
            raise HTTPException(status_code=500, detail="数据库连接未初始化")
        async with async_session() as session:
            # 检查用户名是否已存在
            result = await session.execute(select(User).where(User.username == user_data.username))
            if result.scalar_one_or_none():
                logger.info("注册尝试：用户名 '%s' 已存在", user_data.username)
                raise HTTPException(status_code=400, detail="用户名已存在")
            # 创建用户
            hashed_pw = get_password_hash(user_data.password)
            new_user = User(username=user_data.username, hashed_password=hashed_pw)
            session.add(new_user)
            await session.commit()
            await session.refresh(new_user)
            logger.info("新用户注册成功: %s (id=%s)", user_data.username, new_user.id)
            # 签发 Token
            access_token = create_access_token(data={"sub": new_user.id})
            return {"access_token": access_token, "user_id": new_user.id, "token_type": "bearer"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("注册过程发生异常: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"注册失败: {str(e)}")


@router.post("/login")
async def login(user_data: UserLogin):
    async_session = get_async_session()
    if async_session is None:
        logger.error("登录时 async_session 为 None")
        raise HTTPException(status_code=500, detail="数据库连接未初始化")
    async with async_session() as session:
        result = await session.execute(select(User).where(User.username == user_data.username))
        user = result.scalar_one_or_none()
        if not user or not verify_password(user_data.password, user.hashed_password):
            logger.info("登录失败: 用户名 '%s' 不存在或密码错误", user_data.username)
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        access_token = create_access_token(data={"sub": user.id})
        logger.info("用户 '%s' 登录成功", user_data.username)
        return {"access_token": access_token, "user_id": user.id, "token_type": "bearer"}