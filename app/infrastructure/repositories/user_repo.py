"""
用户 (User) Repository。
"""
import logging
from typing import Optional

from sqlalchemy import select

from app.infrastructure.repositories.base import BaseRepository
from app.models.user import User

logger = logging.getLogger(__name__)


class UserRepository(BaseRepository[User]):
    model_class = User

    async def find_by_username(self, username: str) -> Optional[User]:
        """按用户名查找。"""
        result = await self.session.execute(
            select(User).where(User.username == username)
        )
        return result.scalar_one_or_none()

    async def find_by_id(self, user_id: str) -> Optional[User]:
        """按 ID 查找。"""
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()
