"""
全局中间件注册。

在 build_app 时调用 register_middleware(app) 即可。
"""
import time
import uuid
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)


def register_middleware(app: FastAPI) -> None:
    """注册所有全局中间件。"""

    # CORS — 生产环境应限制 allow_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request ID + Timing（可选）
    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        request_id = str(uuid.uuid4())[:8]
        request.state.request_id = request_id
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        if elapsed > 1000:
            logger.warning("慢请求: %s %s — %.0fms", request.method, request.url.path, elapsed)
        return response
