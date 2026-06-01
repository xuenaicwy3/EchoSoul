import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncEngine
from sqlalchemy.orm import DeclarativeBase
from app.config import Settings

engine: AsyncEngine | None = None
async_session = None

class Base(DeclarativeBase):
    pass

# 分区表支持的配置
PARTITION_TABLES = ["chat_history"]

async def init_db(settings: Settings):
    global engine, async_session
    logging.info(f"[InitDB] 开始连接数据库: {settings.DATABASE_URL}")  # 打印连接字符串
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        pool_size=5,
        max_overflow=5
    )
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        # 1. 确保扩展和普通表（如 affection）存在
        await conn.run_sync(Base.metadata.create_all,
                            tables=[t for name, t in Base.metadata.tables.items() if name not in PARTITION_TABLES])
        # 2. 检查并迁移 chat_history 到分区表
        await _ensure_partitioned_chat_history(conn)
    logging.info("[InitDB] 数据库表创建完成，async_session 已设置")  # 成功标记


async def _ensure_partitioned_chat_history(conn):
    """检查 chat_history 表，如果不是分区表则自动迁移"""
    # 检查表是否存在
    result = await conn.execute(text("""
        SELECT relkind FROM pg_class WHERE relname = 'chat_history' AND relnamespace = 'public'::regnamespace
    """))
    row = result.fetchone()
    if row is None:
        # 表不存在，直接创建分区表
        await _create_partitioned_table(conn)
        return

    # 兼容不同驱动返回的字节/字符串
    relkind = row[0]
    if isinstance(relkind, bytes):
        relkind = relkind.decode()

    if relkind == 'p':
        logging.info("chat_history 已经是分区表，无需迁移")
        return
    elif relkind == 'r':
        logging.info("检测到普通表 chat_history，开始迁移到分区表...")
        # 备份旧数据
        await conn.execute(text("""
            CREATE TEMP TABLE chat_history_backup ON COMMIT DROP AS SELECT * FROM chat_history
        """))
        # 删除旧表（注意 CASCADE 会删除依赖，这里我们手动删除）
        await conn.execute(text("DROP TABLE IF EXISTS chat_history CASCADE"))
        # 创建分区表
        await _create_partitioned_table(conn)
        # 恢复数据
        await conn.execute(text("INSERT INTO chat_history SELECT * FROM chat_history_backup"))
        logging.info("迁移完成，旧数据已保留")
    else:
        raise ValueError(f"未知的表类型: {relkind}")


async def _create_partitioned_table(conn):
    """创建分区表 chat_history 及其分区"""
    # 创建主表
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
    # 创建分区
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
    # 创建索引
    await conn.execute(text("""
        CREATE INDEX idx_chat_history_user_role_time ON chat_history (user_id, role_type, timestamp DESC)
    """))
    logging.info("分区表 chat_history 创建完成")



async def close_db():
    global engine
    if engine:
        await engine.dispose()
        engine = None


def get_async_session():
    if async_session is None:
        raise RuntimeError("数据库未初始化，请先调用 init_db")
    return async_session