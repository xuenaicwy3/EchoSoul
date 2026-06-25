"""
全局异常处理器注册。
"""
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.exceptions import EchoSoulException

logger = logging.getLogger(__name__)


def register_error_handlers(app: FastAPI) -> None:
    """注册全局异常处理。"""

    @app.exception_handler(EchoSoulException)
    async def business_exception_handler(request: Request, exc: EchoSoulException):
        logger.error("业务异常: %s", exc, exc_info=True)
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.critical("未捕获异常: %s", exc, exc_info=True)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})
