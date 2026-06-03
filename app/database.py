"""
数据库引擎与连接池管理（高并发优化版）
"""
import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncEngine
from sqlalchemy.orm import DeclarativeBase
from app.config import Settings

# 全局引擎和会话工厂
engine: AsyncEngine | None = None
async_session = None

class Base(DeclarativeBase):
    pass

PARTITION_TABLES = ["chat_history"]

async def init_db(settings: Settings):
    """
    初始化数据库引擎和会话工厂。
    配置了针对高并发优化的连接池参数，确保在数千用户同时访问时连接不会耗尽。
    """
    global engine, async_session
    logging.info("正在初始化数据库连接（高并发模式）...")
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        pool_size=50,               # 常驻连接数，可根据负载调整
        max_overflow=30,            # 允许溢出的最大连接数，峰值可达 80 连接
        pool_recycle=3600,          # 连接回收时间（秒），避免长时间占用
        pool_pre_ping=True,         # 每次从池中取出连接时检查有效性，防止使用断连
        pool_timeout=30,            # 获取连接的超时时间，避免在高负载下无限等待
    )
    async_session = async_sessionmaker(
        engine,
        expire_on_commit=False,     # 提交后不使对象过期，减少查询
        autoflush=False,            # 手动控制 flush，减少不必要的数据库交互
    )
    logging.info("async_session 已创建（pool_size=50, max_overflow=30）")

    # 创建表及分区迁移
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_partitioned_chat_history(conn)
        # 防止主键序列冲突
        await conn.execute(text(
            "SELECT setval('chat_history_id_seq', COALESCE((SELECT MAX(id) FROM chat_history), 1))"
        ))
    logging.info("数据库初始化完成，准备就绪")


# ... 以下 _ensure_partitioned_chat_history 和 _create_partitioned_table 函数保持原样，无需修改 ...
async def _ensure_partitioned_chat_history(conn):
    """检查 chat_history 表，如果不是分区表则自动迁移"""
    result = await conn.execute(text("""
        SELECT relkind FROM pg_class WHERE relname = 'chat_history' AND relnamespace = 'public'::regnamespace
    """))
    row = result.fetchone()
    if row is None:
        await _create_partitioned_table(conn)
        return

    relkind = row[0]
    if isinstance(relkind, bytes):
        relkind = relkind.decode()

    if relkind == 'p':
        logging.info("chat_history 已经是分区表，无需迁移")
        return
    elif relkind == 'r':
        logging.info("检测到普通表 chat_history，开始迁移到分区表...")
        await conn.execute(text("""
            CREATE TEMP TABLE chat_history_backup ON COMMIT DROP AS SELECT * FROM chat_history
        """))
        await conn.execute(text("DROP TABLE IF EXISTS chat_history CASCADE"))
        await _create_partitioned_table(conn)
        await conn.execute(text("INSERT INTO chat_history SELECT * FROM chat_history_backup"))
        logging.info("迁移完成，旧数据已保留")
    else:
        raise ValueError(f"未知的表类型: {relkind}")


async def _create_partitioned_table(conn):
    """创建分区表 chat_history 及其分区"""
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
    roles = [
        '日系动漫型', '高冷御姐型', '傲娇辣妹型',
        '甜美校花型', '软萌可爱型', '温柔贤淑型',
        '元气少女型', '清冷仙气型'
    ]
    for role in roles:
        table_name = f"chat_history_{role}"
        await conn.execute(text(f"""
            CREATE TABLE {table_name} PARTITION OF chat_history FOR VALUES IN ('{role}')
        """))
    await conn.execute(text("""
        CREATE INDEX idx_chat_history_user_role_time ON chat_history (user_id, role_type, timestamp DESC)
    """))
    logging.info("分区表 chat_history 创建完成")


async def close_db():
    """关闭数据库连接池"""
    global engine
    if engine:
        await engine.dispose()
        engine = None


def get_async_session():
    """
    获取当前可用的异步会话工厂。
    如果未初始化，抛出 RuntimeError 提示调用 init_db。
    """
    if async_session is None:
        raise RuntimeError("数据库未初始化，请先调用 init_db")
    return async_session