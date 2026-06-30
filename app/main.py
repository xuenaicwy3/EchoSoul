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
from app.api.routers import chat, chat_stream, ws, voice
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

# 后台任务引用
_postprocess_task: asyncio.Task | None = None
_mcp_manager = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。"""
    global _postprocess_task, _mcp_manager

    # ---- 启动 ----
    await init_db(settings)
    await init_redis(settings)

    game_svc = GameService(settings)
    await game_svc.init_game_data()

    # 启动后处理 Stream Consumer
    from app.workers.postprocess import run_postprocess_consumer
    _postprocess_task = asyncio.create_task(run_postprocess_consumer())

    # MCP 生命周期由 Celery Worker 中的 AgentHarness 管理，不在此处启动
    proactive_scheduler.start()
    logger.info("所有后台服务已启动 (Harness 架构)")
    yield

    # ---- 关闭 ----
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
    app.include_router(chat_stream.router, dependencies=auth_deps)

    # WebSocket 路由
    app.include_router(ws.router)
    app.include_router(voice.router)

    # ---- 旧路由兼容 ----
    from app.routers import auth_router, game_router, story_router, affective_memory_router
    app.include_router(auth_router.router)
    app.include_router(game_router.router, dependencies=auth_deps)
    app.include_router(story_router.router, dependencies=auth_deps)
    app.include_router(affective_memory_router.router, dependencies=auth_deps)

    # ---- SPA: API 路由之后，所有剩余路径返回 React index.html ----
    _index_html = _static_dir / "index.html"
    if not _index_html.exists():
        logger.warning("React build 未找到！请先执行: cd frontend && npm run build")

    if _index_html.exists():
        # 静态资源
        if (_static_dir / "assets").exists():
            app.mount("/assets", StaticFiles(directory=str(_static_dir / "assets")), name="assets")

        # Live2D 模型文件
        if (_static_dir / "live2d").exists():
            app.mount("/live2d", StaticFiles(directory=str(_static_dir / "live2d")), name="live2d")

        # 3D GLB 模型文件
        if (_static_dir / "glb").exists():
            app.mount("/glb", StaticFiles(directory=str(_static_dir / "glb")), name="glb")
        # VRM 模型文件
        if (_static_dir / "vrm").exists():
            app.mount("/vrm", StaticFiles(directory=str(_static_dir / "vrm")), name="vrm")

        # 所有前端页面路由 → 返回 React index.html
        spa = lambda: FileResponse(str(_index_html))
        app.add_api_route("/", spa, methods=["GET"], include_in_schema=False)
        app.add_api_route("/login", spa, methods=["GET"], include_in_schema=False)
        app.add_api_route("/register", spa, methods=["GET"], include_in_schema=False)
        app.add_api_route("/home", spa, methods=["GET"], include_in_schema=False)
        app.add_api_route("/chat", spa, methods=["GET"], include_in_schema=False)
        app.add_api_route("/game", spa, methods=["GET"], include_in_schema=False)
        app.add_api_route("/story", spa, methods=["GET"], include_in_schema=False)
        app.add_api_route("/memory", spa, methods=["GET"], include_in_schema=False)
    else:
        @app.get("/", include_in_schema=False)
        async def root():
            return FileResponse(str(_static_dir / "login.html"))

    logger.info("FastAPI 应用构建完成")
    return app
