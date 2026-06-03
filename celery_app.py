# celery_app.py
import logging
import os
from celery import Celery
from app.config import Settings

# 加载配置
settings = Settings()

# 创建 Celery 实例
celery_app = Celery(
    'echosoul',
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=['app.tasks']   # 任务模块路径
)

# Celery 配置优化
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='Asia/Shanghai',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,          # 30分钟超时
    task_soft_time_limit=25 * 60,     # 25分钟软超时
    worker_prefetch_multiplier=1,     # 每次只预取一个任务，避免堆积
    result_expires=3600,              # 结果保留1小时
    task_acks_late=True,              # 任务完成后才确认
    task_reject_on_worker_lost=True,
    # 可选：限制任务速率（根据百炼 API 限流调整）
    task_annotations={
        'app.tasks.process_chat': {'rate_limit': '2/s'}
    }
)

# 可选：自动发现任务（已通过 include 指定）
celery_app.autodiscover_tasks(['app'])

# 用于检查配置是否加载成功（调试用）
if __name__ == '__main__':
    logging.info("Celery app configured with broker:", celery_app.conf.broker_url)