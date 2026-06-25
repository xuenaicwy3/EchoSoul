"""
FastAPI 应用主入口。

使用工厂函数 create_app() 构建应用实例。
所有服务在 lifespan 中初始化，路由在 build_app 中注册。
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path
import asyncio

from fastapi import FastAPI, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.deps import auth_deps
from app.api.middleware import register_middleware
from app.api.error_handlers import register_error_handlers
from app.api.routers import chat, ws
from app.core.config import get_settings
from app.core.logging_config import setup_logging
from app.infrastructure.database import init_db, close_db
from app.infrastructure.redis import init_redis, close_redis
from app.game_service import GameService
from app.workers.scheduler import ProactiveScheduler
from app.domain.affection.service import AffectionService

# 导入事件处理器（副作用，触发注册）
import app.workers.postprocess  # noqa: F401

logger = logging.getLogger(__name__)

# ---- FastAPI 工厂 ----
settings = get_settings()
setup_logging(settings.LOG_LEVEL)

# 静态文件目录
_static_dir = Path(__file__).parent / "static"

# 模块级调度器实例
proactive_scheduler = ProactiveScheduler(settings, AffectionService())

# 后处理 Stream Consumer task（在 lifespan 中启动后赋值）
_postprocess_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。"""
    global _postprocess_task

    # 启动
    await init_db(settings)
    await init_redis(settings)

    game_svc = GameService(settings)
    await game_svc.init_game_data()

    # 启动后处理 Stream Consumer（Celery → EventBus 桥接）
    from app.workers.postprocess import run_postprocess_consumer
    _postprocess_task = asyncio.create_task(run_postprocess_consumer())

    proactive_scheduler.start()
    logger.info("所有后台服务已启动")
    yield
    # 关闭
    if _postprocess_task:
        _postprocess_task.cancel()
    proactive_scheduler.shutdown()
    await close_redis()
    await close_db()
    logger.info("所有后台服务已关闭")


def create_app() -> FastAPI:
    """应用工厂函数。"""
    app = FastAPI(title="EchoSoul API", lifespan=lifespan)

    # 全局中间件
    register_middleware(app)

    # 全局异常处理
    register_error_handlers(app)

    # ---- API 路由（需要认证） ----
    app.include_router(chat.router, dependencies=auth_deps)

    # WebSocket 路由
    app.include_router(ws.router)

    # ---- 页面路由（无需认证） ----
    @app.get("/login")
    async def login_page():
        return FileResponse(str(_static_dir / "login.html"))

    @app.get("/register")
    async def register_page():
        return FileResponse(str(_static_dir / "register.html"))

    @app.get("/home")
    async def home_page():
        return FileResponse(str(_static_dir / "home.html"))

    @app.get("/chat")
    async def chat_page():
        return FileResponse(str(_static_dir / "chat.html"))

    @app.get("/game")
    async def game_page():
        return FileResponse(str(_static_dir / "game.html"))

    @app.get("/story_page")
    async def story_page():
        return FileResponse(str(_static_dir / "story.html"))

    @app.get("/")
    async def root():
        return FileResponse(str(_static_dir / "login.html"))

    # ---- 旧路由兼容（逐步迁移到独立 router） ----
    from app.routers import auth_router, game_router, story_router, affective_memory_router
    app.include_router(auth_router.router)
    app.include_router(game_router.router, dependencies=auth_deps)
    app.include_router(story_router.router, dependencies=auth_deps)
    app.include_router(affective_memory_router.router, dependencies=auth_deps)

    # 静态文件挂载
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

    logger.info("FastAPI 应用构建完成")
    return app
