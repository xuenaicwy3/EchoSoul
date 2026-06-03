"""
自定义检查点表初始化（不使用 LangGraph 默认的 setup，避免 CREATE INDEX CONCURRENTLY 死锁）
"""
import logging

logger = logging.getLogger(__name__)

CHECKPOINT_DDL = """
CREATE TABLE IF NOT EXISTS checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    type TEXT,
    checkpoint JSONB NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);

CREATE TABLE IF NOT EXISTS checkpoint_writes (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    channel TEXT NOT NULL,
    type TEXT,
    value BYTEA,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
);

-- 使用普通索引（不用 CONCURRENTLY），可在事务中安全执行
CREATE INDEX IF NOT EXISTS idx_checkpoints_thread_id ON checkpoints (thread_id, checkpoint_ns);
"""

async def init_checkpoint_tables(conn):
    """执行建表语句，自动处理重复执行"""
    try:
        async with conn.cursor() as cur:
            await cur.execute(CHECKPOINT_DDL)
        logger.info("检查点表初始化完成")
    except Exception as e:
        logger.error(f"检查点表初始化失败: {e}")
        raise