import asyncio
from celery import Celery
from celery.signals import worker_ready
from app.config import Settings
from app.database import init_db, close_db
from app.redis_client import init_redis, close_redis

settings = Settings()

celery_app = Celery(
    'echosoul',
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=['app.tasks']
)

celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='Asia/Shanghai',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,
    task_soft_time_limit=25 * 60,
    worker_prefetch_multiplier=1,
    result_expires=3600,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_annotations={
        'app.tasks.process_chat': {'rate_limit': '2/s'}
    }
)

@worker_ready.connect
def on_worker_ready(**kwargs):
    """Worker 启动后，初始化数据库（仅用于检查点）和 Redis"""
    async def _init():
        # 初始化异步引擎（用于数据库后处理？不，这里不需要后处理，只需检查点）
        # 实际上 PostgresSaver 使用同步连接，不需要异步引擎
        pass
    # 这里不需要 asyncio.run，因为 init_db 是异步的，但检查点用同步连接。
    # 我们可以在 tasks.py 中创建 PostgresSaver 时使用同步连接。
    print("[Celery Worker] Worker 就绪")

