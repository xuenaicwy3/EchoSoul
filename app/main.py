"""
FastAPI 应用主模块
使用 EchoSoulAPI 类封装应用构建、路由注册、中间件和异常处理。
通过实例方法挂载路由，避免使用装饰器，便于依赖注入和测试。
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from app.checkpoint_setup import init_checkpoint_tables

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.params import Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from celery.result import AsyncResult
from app.celery_app import celery_app
from app.tasks import process_chat
from app.database import init_db, close_db
from app.redis_client import init_redis, close_redis, get_task_result, publish_chat_task, redis_client
from app.config import Settings
from app.logging_config import setup_logging
from app.agent import EchoSoulAgent
from app.emotions import EmotionService
from app.memory import MemoryService
from app.affection import AffectionService
from app.scheduler import ProactiveScheduler
from app.models.schemas import ChatRequest, ChatResponse, AffectionResponse, AgentState
from app.exceptions import EchoSoulException
from langchain_core.runnables import RunnableConfig
from app.roles import RoleCatalog
from app.chat_history import ChatHistoryManager
from app.dependencies import get_current_user
from app.routers import auth_router
from app.models.user import User
from app.redis_client import get_task_result as redis_get_task_result
from app.redis_saver import RedisSaver
import uuid
import json
from app.tasks import process_chat
from celery.result import AsyncResult
from app.celery_app import celery_app
from app.tasks import process_chat
from app.worker import process_postprocess_stream
from app.routers import game_router  # 新增游戏化路由
from app.game_service import GameService

logger = logging.getLogger(__name__)


class EchoSoulAPI:
    """EchoSoul 应用核心类，负责组装服务、注册路由并返回 FastAPI 实例"""

    def __init__(self):
        # ---------- 1. 加载配置 ----------
        self.settings = Settings()
        setup_logging(self.settings)
        logger.info("正在初始化 EchoSoulAPI ...")

        # ---------- 2. 实例化所有依赖服务（依赖注入） ----------
        self.emotion_service = EmotionService(self.settings)
        self.affection_service = AffectionService()
        self.memory_service = MemoryService(self.settings)          # 直接创建记忆服务
        self.scheduler = ProactiveScheduler(self.settings, self.affection_service)

        # 创建 Agent 时传入真实记忆服务
        self.agent = EchoSoulAgent(
            self.settings,
            self.emotion_service,
            memory_svc=self.memory_service,          # 传入真实服务
            affection_svc=self.affection_service,
        )
        self.chat_history = ChatHistoryManager()
        # 静态文件目录
        self.static_dir = Path(__file__).parent / "static"
        logger.info("所有服务已实例化")

    # ---------- 生命周期 ----------
    @asynccontextmanager
    async def lifespan(self, app: FastAPI):
        """应用生命周期：启动时初始化数据库、Redis，启动后处理 Worker"""
        await init_db(self.settings)
        await init_redis(self.settings)

        # ----- 初始化游戏化种子数据 -----
        game_svc = GameService(self.settings)
        await game_svc.init_game_data()
        # -------------------------------

        # 启动后处理 Worker（唯一操作记忆的协程，避免多进程竞争）
        self.postprocess_task = asyncio.create_task(process_postprocess_stream(self.agent))
        self.scheduler.start()
        logger.info("后台服务已启动")
        yield
        self.postprocess_task.cancel()
        self.scheduler.shutdown()
        await close_redis()
        await close_db()
        logger.info("后台服务已关闭")



    # ---------- 路由处理方法（无需装饰器，后续手动注册） ----------
    async def root(self) -> FileResponse:
        """
        根路由：返回前端聊天页面。
        使用 build_app 中计算的绝对路径，确保任何工作目录下都能找到静态文件。
        """
        if not self.static_dir:
            # 兜底：若未设置，则基于本文件路径计算
            self.static_dir = Path(__file__).parent / "static"
        return FileResponse(self.static_dir / "index.html")


    # chat 方法：仅发布任务，返回 task_id
    async def chat(self, req: ChatRequest, current_user: str = Depends(get_current_user)):
        """
        异步聊天接口。
        1. 预处理用户消息（角色选择等）。
        2. 获取当前角色、好感度信息。
        3. 构造任务负载，发布至 Celery Worker 进行异步 AI 生成。
        4. 立即返回 task_id，由前端轮询结果。
        """
        logger.info("收到异步聊天请求: user=%s, msg=%s", current_user, req.message[:30])

        # 更新用户活跃时间（Redis）
        try:
            await self.scheduler.update_active(current_user)
        except Exception as e:
            logger.error("更新活跃时间失败: %s", e)

        # ---------- 1. 预处理：[ROLE_SELECT] 指令 ----------
        preset_role = None
        preset_greeting = None
        user_input = req.message

        if user_input.startswith("[ROLE_SELECT]"):
            preset_role = user_input.replace("[ROLE_SELECT]", "").strip()
            role = RoleCatalog.get_role(preset_role)
            preset_greeting = role.greeting
            user_input = ""
            logger.info("[chat] 角色选择指令: %s", preset_role)

        # ---------- 2. 从历史状态恢复当前角色 ----------
        try:
            last = self.agent.graph.get_state({"configurable": {"thread_id": current_user}})
            vals = last.values if last else {}
        except Exception as e:
            logger.warning("无法获取历史状态: %s", e)
            vals = {}

        final_role = req.role_type or preset_role or vals.get("role_type")

        # 生成 thread_id，用于隔离不同角色的对话历史
        thread_id = f"{current_user}:{final_role}" if final_role else current_user

        # ---------- 3. 异步获取好感度信息 ----------
        aff_info, unlock_info = await self._get_affection_info(current_user, final_role)

        # ---------- 4. 构造 Celery 任务参数 ----------
        task_payload = {
            "user_id": current_user,
            "role_type": final_role,
            "user_input": user_input,
            "preset_greeting": preset_greeting,
            "aff_info": aff_info,
            "unlock_info": unlock_info,
            "thread_id": thread_id,
            "need_regenerate": False,
            "regenerate_context": None,
        }

        # ---------- 5. 处理“重新生成”请求 ----------
        negative_kws = ["不满意", "不认同", "重新说", "换一个", "不想听", "不对"]
        if any(kw in req.message for kw in negative_kws):
            try:
                last = self.agent.graph.get_state({"configurable": {"thread_id": thread_id}})
                vals = last.values if last else {}
            except Exception as e:
                logger.warning("获取历史状态用于重新生成时出错: %s", e)
                vals = {}
            if vals.get("final_response"):
                task_payload["need_regenerate"] = True
                task_payload["regenerate_context"] = {
                    "user_msg": vals.get("user_input", ""),
                    "ai_msg": vals.get("final_response", "")
                }
                logger.info("[chat] 触发重新生成，原回复: %s", vals.get("final_response", "")[:30])

        # ---------- 6. 发布 Celery 任务 ----------
        try:
            # Celery 的 delay 方法直接传递字典，会自动序列化为 JSON
            celery_task = process_chat.delay(task_payload)
            logger.info("[chat] Celery 任务已发布: task_id=%s, user=%s", celery_task.id, current_user)
            return {"task_id": celery_task.id}
        except Exception as e:
            logger.critical("无法发布 Celery 任务: %s", e)
            raise HTTPException(status_code=503, detail="服务暂时不可用，请稍后重试")


    # 新增轮询接口
    async def get_chat_result(self, task_id: str):
        try:
            task_result = AsyncResult(task_id, app=celery_app)
            if task_result.ready():
                if task_result.successful():
                    # 任务成功，直接返回结果字典
                    return task_result.result
                else:
                    # 任务失败，返回错误信息
                    return {"error": str(task_result.info)}
            else:
                return {"status": "pending"}
        except Exception as e:
            logger.error(f"获取任务结果失败: {e}")
            return {"error": "内部错误"}

    async def game_page(self):
        """游戏中心页面"""
        return FileResponse(str(self.static_dir / "game.html"))


    # ---------- 新增异步接口 ----------
    async def chat_async(self, req: ChatRequest, current_user: str = Depends(get_current_user)):
        logger.info("异步聊天请求: user=%s, msg=%s", current_user, req.message[:30])
        task = process_chat.delay(
            user_id=current_user,
            message=req.message,
            role_type=req.role_type
        )
        return {"task_id": task.id, "status": "pending"}

    async def get_chat_result(self, task_id: str):
        result = AsyncResult(task_id, app=celery_app)
        if result.ready():
            if result.successful():
                data = result.result
                return ChatResponse(
                    reply=data["reply"],
                    emotion=data["emotion"],
                    role=data["role"]
                )
            else:
                return JSONResponse(
                    status_code=500,
                    content={"detail": f"任务执行失败: {str(result.info)}"}
                )
        else:
            return {"status": "processing", "task_id": task_id}


    async def _get_affection_info(self, role_type: str, current_user: str = Depends(get_current_user)) -> tuple[str, str]:
        """获取预计算的好感度文本"""
        aff_info = "亲密度10, 信任10"
        unlock_info = ""
        if not role_type:
            return aff_info, unlock_info
        try:
            aff = await self.affection_service.get(current_user, role_type)
            unl = await self.affection_service.get_unlock_state(current_user, role_type)
            aff_info = f"亲密度{aff['intimacy']:.0f}, 信任{aff['trust']:.0f}"
            if unl["level"] >= 2:
                unlock_info += "关系亲密，说话更随意。"
            if unl["story_unlocked"]:
                unlock_info += "可分享角色小秘密。"
            if unl["avatar_upgraded"]:
                unlock_info += "角色换了新衣服。"
        except Exception as e:
            logger.error("获取好感度失败: %s", e)
        return aff_info, unlock_info


    async def get_affection(self, role_type: str, current_user: str = Depends(get_current_user)) -> AffectionResponse:
        """好感度查询接口"""
        aff = await self.affection_service.get(current_user, role_type)
        unl = await self.affection_service.get_unlock_state(current_user, role_type)
        unlocks = []
        if unl["level"] >= 1:
            unlocks.append("语气升级")
        if unl["level"] >= 2:
            unlocks.append("昵称特权")
        if unl["story_unlocked"]:
            unlocks.append("角色故事")
        if unl["avatar_upgraded"]:
            unlocks.append("新形象")
        return AffectionResponse(
            intimacy=aff["intimacy"],
            trust=aff["trust"],
            fun=aff["fun"],
            growth=aff["growth"],
            level=unl["level"],
            unlocks=unlocks,
        )

    async def get_active_messages(self, current_user: str = Depends(get_current_user)) -> dict:
        """主动消息获取接口"""
        msgs = await self.scheduler.get_pending(current_user)
        return {"messages": msgs}

    async def get_chat_history(self, role_type: str, before: str = None, current_user: str = Depends(get_current_user)):
        """查询指定角色下的聊天历史"""
        limit = 50
        history = await self.chat_history.get_history(current_user, role_type, limit=limit, before=before)
        return {"history": history}

    async def delete_chat_history(self, role_type: str, current_user: str = Depends(get_current_user)):
        """删除聊天历史"""
        await self.chat_history.delete_history(current_user, role_type)
        return {"status": "ok"}


    async def login_page(self):
        return FileResponse(str(self.static_dir / "login.html"))

    async def register_page(self):
        return FileResponse(str(self.static_dir / "register.html"))

    async def home_page(self):
        return FileResponse(str(self.static_dir / "home.html"))

    async def chat_page(self, request: Request):
        # 聊天页面通过URL参数传递角色，前端会解析
        return FileResponse(str(self.static_dir / "chat.html"))


    # ---------- 构建 FastAPI 应用 ----------
    def build_app(self) -> FastAPI:
        """
        创建 FastAPI 实例，注册中间件、异常处理和所有路由。
        计算静态文件目录的绝对路径，确保在任何工作目录下都能正确访问。
        """
        # 获取当前文件所在目录（app/）的父级静态目录
        base_dir = Path(__file__).parent
        self.static_dir = base_dir / "static"
        logger.debug("静态文件目录: %s", self.static_dir)

        app = FastAPI(title="EchoSoul API", lifespan=self.lifespan)
        app.include_router(auth_router.router)  # 注册 /auth/register 和 /auth/login

        # ---------- 全局中间件 ----------
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # ---------- 全局异常处理器 ----------
        @app.exception_handler(EchoSoulException)
        async def echo_exception_handler(request: Request, exc: EchoSoulException):
            logger.error("业务异常: %s", exc, exc_info=True)
            return JSONResponse(status_code=400, content={"detail": str(exc)})

        @app.exception_handler(Exception)
        async def global_exception_handler(request: Request, exc: Exception):
            logger.critical("未捕获异常: %s", exc, exc_info=True)
            return JSONResponse(status_code=500, content={"detail": "Internal server error"})

        # ---------- API 路由（需要认证） ----------
        # 需要认证的路由统一添加 dependencies
        auth_deps = [Depends(get_current_user)]
        app.add_api_route(
            "/chat",
            self.chat,
            methods=["POST"],
            dependencies=auth_deps
        )
        app.add_api_route(
            "/affection/{role_type}",
            self.get_affection,
            methods=["GET"],
            response_model=AffectionResponse,
            dependencies=auth_deps
        )
        app.add_api_route(
            "/active_messages",
            self.get_active_messages,
            methods=["GET"],
            dependencies=auth_deps
        )

        # 在 build_app 方法内，其他路由注册之后添加
        app.add_api_route(
            "/chat_history/{role_type}",
            self.get_chat_history,
            methods=["GET"],
            dependencies=auth_deps
        )

        app.add_api_route(
            "/chat_history/{role_type}",
            self.delete_chat_history,
            methods=["DELETE"],
            dependencies=auth_deps
        )

        app.add_api_route(
            "/chat/result/{task_id}",
            self.get_chat_result,
            methods=["GET"],
            dependencies=auth_deps
        )


        app.include_router(game_router.router, dependencies=[Depends(get_current_user)])

        # ---------- 页面路由（无需认证） ----------
        app.add_api_route("/login", self.login_page, methods=["GET"])
        app.add_api_route("/register", self.register_page, methods=["GET"])
        app.add_api_route("/home", self.home_page, methods=["GET"])
        app.add_api_route("/chat", self.chat_page, methods=["GET"])  # 注意：GET /chat 返回聊天页面
        app.add_api_route("/", self.login_page, methods=["GET"])  # 根路径默认到登录页
        app.add_api_route("/game", self.game_page, methods=["GET"])  # 新增游戏中心页面
        # 将 /static 路径映射到实际的静态文件目录
        app.mount("/static", StaticFiles(directory=str(self.static_dir)), name="static")


        logger.info("FastAPI 应用构建完成")
        return app



def create_app() -> FastAPI:
    """应用工厂函数，供 uvicorn 以 factory=True 方式调用"""
    app_instance = EchoSoulAPI()
    return app_instance.build_app()