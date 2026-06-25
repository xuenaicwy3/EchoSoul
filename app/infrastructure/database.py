"""
数据库引擎与连接池管理。

管理全局 AsyncEngine 和 async_sessionmaker 的生命周期。
所有异步数据库操作通过 get_async_session() 获取会话工厂。
"""
import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings
from app.models.db_models import Base

logger = logging.getLogger(__name__)

# 全局引擎和会话工厂
_engine: Optional[AsyncEngine] = None
_async_session_factory: Optional[async_sessionmaker[AsyncSession]] = None

# 需要分区管理的表
PARTITION_TABLES = ["chat_history"]

# 预设角色类型（用于分区表创建）
ROLE_TYPES = [
    "日系动漫型", "高冷御姐型", "傲娇辣妹型",
    "甜美校花型", "软萌可爱型", "温柔贤淑型",
    "元气少女型", "清冷仙气型",
]


async def init_db(settings: Settings) -> None:
    """初始化数据库引擎、创建表和分区。"""
    global _engine, _async_session_factory

    logger.info("正在初始化数据库连接...")
    _engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        pool_size=50,
        max_overflow=30,
        pool_recycle=3600,
        pool_pre_ping=True,
        pool_timeout=30,
    )
    _async_session_factory = async_sessionmaker(
        _engine,
        expire_on_commit=False,
        autoflush=False,
    )
    logger.info("async_session 已创建 (pool_size=50, max_overflow=30)")

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_partitioned_chat_history(conn)
        await conn.execute(text(
            "SELECT setval('chat_history_id_seq', "
            "COALESCE((SELECT MAX(id) FROM chat_history), 1))"
        ))
    logger.info("数据库初始化完成")


async def close_db() -> None:
    """关闭数据库连接池。"""
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None
        logger.info("数据库连接池已关闭")


def get_async_session() -> async_sessionmaker[AsyncSession]:
    """获取异步会话工厂。若未初始化则抛出异常。"""
    if _async_session_factory is None:
        raise RuntimeError("数据库未初始化，请先调用 init_db()")
    return _async_session_factory


# ---- 分区表管理（内部实现） ----

async def _ensure_partitioned_chat_history(conn) -> None:
    """检查并确保 chat_history 为分区表。"""
    result = await conn.execute(text(
        "SELECT relkind FROM pg_class "
        "WHERE relname = 'chat_history' AND relnamespace = 'public'::regnamespace"
    ))
    row = result.fetchone()
    if row is None:
        await _create_partitioned_table(conn)
        return

    relkind = row[0]
    if isinstance(relkind, bytes):
        relkind = relkind.decode()

    if relkind == "p":
        logger.info("chat_history 已是分区表，无需迁移")
    elif relkind == "r":
        logger.info("迁移普通表 chat_history 为分区表...")
        await conn.execute(text(
            "CREATE TEMP TABLE chat_history_backup ON COMMIT DROP AS SELECT * FROM chat_history"
        ))
        await conn.execute(text("DROP TABLE IF EXISTS chat_history CASCADE"))
        await _create_partitioned_table(conn)
        await conn.execute(text("INSERT INTO chat_history SELECT * FROM chat_history_backup"))
        logger.info("分区表迁移完成")


async def _create_partitioned_table(conn) -> None:
    """创建 chat_history 分区表及子分区。"""
    await conn.execute(text("""
        CREATE TABLE chat_history (
            id SERIAL,
            user_id TEXT NOT NULL,
            role_type TEXT NOT NULL,
            sender TEXT NOT NULL,
            message TEXT NOT NULL,
            timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id, role_type)
        ) PARTITION BY LIST (role_type)
    """))
    for role in ROLE_TYPES:
        table_name = f"chat_history_{role}"
        await conn.execute(text(
            f"CREATE TABLE {table_name} PARTITION OF chat_history FOR VALUES IN ('{role}')"
        ))
    await conn.execute(text(
        "CREATE INDEX idx_chat_history_user_role_time "
        "ON chat_history (user_id, role_type, timestamp DESC)"
    ))
    logger.info("分区表 chat_history 创建完成")
