"""
FastAPI 应用主模块
使用 EchoSoulAPI 类封装应用构建、路由注册、中间件和异常处理。
通过实例方法挂载路由，避免使用装饰器，便于依赖注入和测试。
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

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
logger = logging.getLogger(__name__)


class EchoSoulAPI:
    """EchoSoul 应用核心类，负责组装服务、注册路由并返回 FastAPI 实例"""

    def __init__(self) -> None:
        # ---------- 1. 加载配置 ----------
        self.settings = Settings()
        setup_logging(self.settings)
        logger.info("正在初始化 EchoSoulAPI ...")
        logger.info("DASHSCOPE_API_KEY 已加载: %s", self.settings.DASHSCOPE_API_KEY + "****")

        # ---------- 2. 实例化所有依赖服务（依赖注入） ----------
        self.emotion_service = EmotionService(self.settings)
        self.memory_service = MemoryService(self.settings)
        self.affection_service = AffectionService(self.settings)
        self.scheduler = ProactiveScheduler(self.settings, self.affection_service)
        self.agent = EchoSoulAgent(
            self.settings,
            self.emotion_service,
            self.memory_service,
            self.affection_service,
        )
        self.chat_history = ChatHistoryManager(self.settings.CHROMA_PATH)
        logger.info("所有服务已实例化")

        # 静态文件目录将在 build_app 中确定
        self.static_dir: Path | None = None


    # ---------- 生命周期（调度器启停） ----------
    @asynccontextmanager
    async def lifespan(self, app: FastAPI):
        """应用生命周期：启动时开启调度器，关闭时关闭调度器"""
        self.scheduler.start()
        logger.info("后台调度器已启动")
        yield
        self.scheduler.shutdown()
        logger.info("后台调度器已关闭")

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

    async def chat(self, req: ChatRequest) -> ChatResponse:
        """聊天接口：接收用户消息，调用 Agent 并返回 AI 回复"""
        logger.info("收到消息: user=%s, msg=%s", req.user_id[:8], req.message[:30])
        self.scheduler.update_active(req.user_id)

        # ---------- 预处理：解析 [ROLE_SELECT] 消息 ----------
        preset_role = None
        preset_greeting = None
        user_input = req.message

        if user_input.startswith("[ROLE_SELECT]"):
            preset_role = user_input.replace("[ROLE_SELECT]", "").strip()
            role = RoleCatalog.get_role(preset_role)
            preset_greeting = role.greeting
            user_input = ""
            logger.info("[Main] 预处理角色选择: %s, 开场白: %s", preset_role, preset_greeting[:20])

        # 从历史状态中恢复角色（使用通用 thread_id 获取最近一次状态，仅用于提取 role_type）
        try:
            last = self.agent.graph.get_state({"configurable": {"thread_id": req.user_id}})
            vals = last.values if last else {}
            # 测试
            logger.info("[Main] last.values: %s, last: %s", vals, last)
        except Exception:
            vals = {}

        # 确定最终角色：前端传入 > 预处理 > 历史状态
        # 角色确定优先级：前端请求字段 > [ROLE_SELECT]解析 > 历史状态
        final_role = req.role_type or preset_role or vals.get("role_type")

        # 为每个角色创建独立的 thread_id，实现对话历史隔离
        thread_id = f"{req.user_id}:{final_role}" if final_role else req.user_id
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        logger.info("[Main] thread_id: %s", thread_id)
        logger.info("[Main] 初始化历史记录: %s", self.agent.graph.get_state({"configurable": {"thread_id": thread_id}}))

        negative_kws = ["不满意", "不认同", "重新说", "换一个", "不想听", "不对"]

        if any(kw in req.message for kw in negative_kws):
            # 用户要求重新生成回复
            try:
                last = self.agent.graph.get_state(config)
                vals = last.values or {}
            except Exception:
                vals = {}

            # 重新生成时使用历史角色，若没有则用 final_role
            regen_role = vals.get("role_type", final_role or "温柔贤淑型")
            logger.info("[Main] regen_role: %s", regen_role)
            logger.info("[Main] emotion: %s, memory_text: %s",
                        vals.get("emotion", {"label": "neutral", "score": 0.5}), vals.get("memory_text", ""))

            regen_state: AgentState = {
                "user_id": req.user_id,
                "user_input": req.message,
                "role_type": regen_role,
                "emotion": vals.get("emotion", {"label": "neutral", "score": 0.5}),
                "memory_text": vals.get("memory_text", ""),
                "final_response": None,
                "need_regenerate": True,
                "regenerate_context": {
                    "user_msg": vals.get("user_input", ""),
                    "ai_msg": vals.get("final_response", ""),
                },
            }
            final = self.agent.invoke(regen_state, config)
        else:
            # 正常对话流程（含角色选择预处理）
            init_state: AgentState  = {
                "user_id": req.user_id,
                "user_input": user_input,
                "role_type": final_role,
                "emotion": vals.get("emotion", {}),
                "memory_text": vals.get("memory_text", ""),
                "final_response": preset_greeting,
                "need_regenerate": False,
                "regenerate_context": None,
            }

            # 调试日志（可保留）
            logger.info("[Main] init_state role_type = %s", init_state.get("role_type"))
            final = self.agent.invoke(init_state, config)

        logger.info("回复: %s", final["final_response"][:30])

        # 在 chat 方法中，return 之前，存储历史之前
        logger.info("准备存储历史，final_role=%s, msg=%s", final_role, req.message[:30])

        # ---------- 存储聊天历史 ----------
        # 用户消息（系统指令不存）
        if not req.message.startswith("[ROLE_SELECT]"):
            self.chat_history.add_message(req.user_id, final_role, "user", req.message)
        # 存储 AI 回复
        if final.get("final_response"):
            self.chat_history.add_message(req.user_id, final_role, "ai", final["final_response"])

        return ChatResponse(
            reply=final["final_response"],
            emotion=final.get("emotion", {}),
            role=final.get("role_type"),
        )

    async def get_affection(self, user_id: str, role_type: str) -> AffectionResponse:
        """好感度查询接口"""
        aff = self.affection_service.get(user_id, role_type)
        unl = self.affection_service.get_unlock_state(user_id, role_type)
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

    async def get_active_messages(self, user_id: str) -> dict:
        """主动消息获取接口"""
        msgs = self.scheduler.get_pending(user_id)
        return {"messages": msgs}

    async def get_chat_history(self, user_id: str, role_type: str):
        """查询指定角色下的聊天历史"""
        history = self.chat_history.get_history(user_id, role_type)
        return {"history": history}

    async def delete_chat_history(self, user_id: str, role_type: str):
        """删除聊天历史"""
        self.chat_history.delete_history(user_id, role_type)
        return {"status": "ok"}

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

        # ---------- 静态文件挂载 ----------
        # 将 /static 路径映射到实际的静态文件目录
        app.mount("/static", StaticFiles(directory=str(self.static_dir)), name="static")

        # ---------- 注册路由 ----------
        app.add_api_route("/", self.root, methods=["GET"])
        app.add_api_route("/chat", self.chat, methods=["POST"], response_model=ChatResponse)
        app.add_api_route(
            "/affection/{user_id}/{role_type}",
            self.get_affection,
            methods=["GET"],
            response_model=AffectionResponse,
        )
        app.add_api_route("/active_messages/{user_id}", self.get_active_messages, methods=["GET"])

        # 在 build_app 方法内，其他路由注册之后添加
        app.add_api_route(
            "/chat_history/{user_id}/{role_type}",
            self.get_chat_history,
            methods=["GET"],
        )

        app.add_api_route(
            "/chat_history/{user_id}/{role_type}",
            self.delete_chat_history,
            methods=["DELETE"],
        )

        logger.info("FastAPI 应用构建完成")
        return app




def create_app() -> FastAPI:
    """应用工厂函数，供 uvicorn 以 factory=True 方式调用"""
    app_instance = EchoSoulAPI()
    return app_instance.build_app()