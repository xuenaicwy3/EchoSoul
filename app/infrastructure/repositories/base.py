"""
Repository 基类。

提供通用的 CRUD 操作模板。所有业务 Repository 继承此类。
使用泛型绑定到具体的 ORM Model 类型。
"""
import logging
from typing import Any, Generic, Optional, Sequence, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# 泛型变量，代表任意 ORM Model
T = TypeVar("T")


class BaseRepository(Generic[T]):
    """Repository 基类。

    封装 AsyncSession 和通用查询方法。
    子类通过 model_class 属性绑定到具体 ORM Model。
    """

    model_class: type[T]  # 子类必须设置

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---- CRUD ----

    async def get_by_id(self, id: Any) -> Optional[T]:
        result = await self.session.execute(
            select(self.model_class).where(self.model_class.id == id)
        )
        return result.scalar_one_or_none()

    async def get_all(self, limit: int = 100, offset: int = 0) -> Sequence[T]:
        result = await self.session.execute(
            select(self.model_class).limit(limit).offset(offset)
        )
        return result.scalars().all()

    async def add(self, entity: T) -> T:
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def add_all(self, entities: list[T]) -> list[T]:
        self.session.add_all(entities)
        await self.session.flush()
        return entities

    async def delete(self, entity: T) -> None:
        await self.session.delete(entity)
        await self.session.flush()

    async def save(self, entity: T) -> T:
        """保存（新增或合并）实体。"""
        merged = await self.session.merge(entity)
        await self.session.flush()
        return merged

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()

    async def count_all(self) -> int:
        """统计总记录数。"""
        from sqlalchemy import func
        result = await self.session.execute(
            select(func.count()).select_from(self.model_class)
        )
        return result.scalar() or 0
