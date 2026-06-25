"""
Celery 应用配置（生产级）。

- Redis 作为 broker 和 result backend
- 任务重试 + 指数退避 + 超时保护
- 限流防止 LLM API 过载
- ack_late 防止任务丢失
"""
from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "echosoul",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks"],
)

celery_app.conf.update(
    # ---- 序列化 ----
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    # ---- 任务执行 ----
    task_track_started=True,
    task_time_limit=60,               # 硬超时 60s（超时强制 kill）
    task_soft_time_limit=50,          # 软超时 50s（抛 SoftTimeLimitExceeded，可用于优雅降级）
    task_acks_late=True,              # 任务完成后才 ACK（防止 Worker 挂掉丢任务）
    task_reject_on_worker_lost=True,  # Worker 挂掉 → 任务重新入队
    # ---- 并发控制 ----
    worker_prefetch_multiplier=1,     # 每次只取 1 个任务，公平分配
    # ---- 结果 ----
    result_expires=600,               # 结果 Redis TTL 10 分钟
    # ---- 限流 ----
    task_annotations={
        "app.tasks.process_chat": {
            "rate_limit": "4/m",      # 每分钟最多 4 个（防 API 限流，可按需调整）
        }
    },
)
