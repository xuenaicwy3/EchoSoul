"""
聊天相关路由。

POST /chat          → Celery 异步发布，立即返回 task_id（不阻塞）
GET  /chat/result/{task_id} → 前端轮询获取结果
GET  /affection/{role_type}  → 好感度查询
GET  /chat_history/{role_type} → 聊天历史
"""
import json
import logging

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.celery_app import celery_app
from app.core.config import get_settings
from app.task_registry import ChatTaskPayload, send_chat_task
from app.domain.affection.service import AffectionService
from app.domain.roles.catalog import RoleCatalog
from app.models.schemas import ChatRequest, AffectionResponse
from app.chat_history import ChatHistoryManager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])
settings = get_settings()


def _get_affection_service() -> AffectionService:
    if not hasattr(_get_affection_service, "_instance"):
        _get_affection_service._instance = AffectionService()
    return _get_affection_service._instance


# ==================== POST /chat ====================


@router.post("/chat")
async def chat(
    req: ChatRequest,
    current_user: str = Depends(get_current_user),
):
    """
    异步聊天接口。

    FastAPI 只做轻量预处理（角色识别、好感度查询），
    重活（LLM 调用、记忆检索）全部交给 Celery Worker。
    立即返回 task_id，前端轮询 GET /chat/result/{task_id}。
    """
    logger.info("收到聊天请求: user=%s msg=%s", current_user, req.message[:30])

    user_input = req.message
    preset_role = None
    preset_greeting = None

    # ---- 1. 角色选择预处理 ----
    if user_input.startswith("[ROLE_SELECT]"):
        preset_role = user_input.replace("[ROLE_SELECT]", "").strip()
        role = RoleCatalog.get_role(preset_role)
        preset_greeting = role.greeting
        user_input = ""
        logger.info("[chat] 角色选择: %s", preset_role)

    final_role = req.role_type or preset_role
    thread_id = f"{current_user}:{final_role}" if final_role else current_user

    # ---- 2. 获取好感度信息（轻量 DB 查询） ----
    aff_info = "亲密度10, 信任10"
    unlock_info = ""
    if final_role:
        try:
            aff_svc = _get_affection_service()
            aff = await aff_svc.get(current_user, final_role)
            unl = await aff_svc.get_unlock_state(current_user, final_role)
            aff_info = f"亲密度{aff['intimacy']:.0f}, 信任{aff['trust']:.0f}"
            if unl["level"] >= 2:
                unlock_info += "关系亲密，说话更随意。"
            if unl["story_unlocked"]:
                unlock_info += "可分享角色小秘密。"
            if unl["avatar_upgraded"]:
                unlock_info += "角色换了新衣服。"
        except Exception as e:
            logger.error("获取好感度失败: %s", e)

    # ---- 3. 重新生成检测 ----
    need_regenerate = False
    negative_kws = ["不满意", "不认同", "重新说", "换一个", "不想听", "不对"]
    if any(kw in req.message for kw in negative_kws):
        need_regenerate = True
        logger.info("[chat] 触发重新生成")

    # ---- 4. 构造 Celery 任务 payload ----
    task_payload = {
        "user_id": current_user,
        "role_type": final_role,
        "user_input": user_input,
        "preset_greeting": preset_greeting,
        "aff_info": aff_info,
        "unlock_info": unlock_info,
        "thread_id": thread_id,
        "need_regenerate": need_regenerate,
    }

    # ---- 5. 发布 Celery 任务（类型安全） ----
    try:
        task_id = send_chat_task(ChatTaskPayload(**task_payload))
        logger.info(
            "[chat] Celery 任务已发布: task_id=%s user=%s role=%s",
            task_id[:8], current_user[:8], final_role,
        )
        return {"task_id": task_id}
    except Exception as e:
        logger.critical("无法发布 Celery 任务: %s", e)
        raise HTTPException(status_code=503, detail="服务暂时不可用，请稍后重试")


# ==================== GET /chat/result/{task_id} ====================


@router.get("/chat/result/{task_id}")
async def get_chat_result(task_id: str):
    """前端轮询：根据 task_id 获取聊天结果。"""
    try:
        task_result = AsyncResult(task_id, app=celery_app)
        if task_result.ready():
            if task_result.successful():
                result = task_result.result
                logger.info("任务 %s 结果: %s", task_id[:8], result.get("reply", "")[:30])
                return result
            else:
                error = str(task_result.info)
                logger.error("任务 %s 失败: %s", task_id[:8], error)
                return {"error": f"任务执行失败: {error}"}
        else:
            return {"status": "pending"}
    except Exception as e:
        logger.error("获取任务结果失败: %s", e)
        return {"error": "内部错误"}


# ==================== 好感度 / 聊天历史 ====================


@router.get("/affection/{role_type}", response_model=AffectionResponse)
async def get_affection(
    role_type: str,
    current_user: str = Depends(get_current_user),
):
    """好感度查询接口。"""
    aff_svc = _get_affection_service()
    aff = await aff_svc.get(current_user, role_type)
    unl = await aff_svc.get_unlock_state(current_user, role_type)
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
        intimacy=aff["intimacy"], trust=aff["trust"], fun=aff["fun"],
        growth=aff["growth"], level=unl["level"], unlocks=unlocks,
    )


@router.get("/chat_history/{role_type}")
async def get_chat_history(
    role_type: str,
    before: str = None,
    current_user: str = Depends(get_current_user),
):
    """查询指定角色的聊天历史。"""
    history = await ChatHistoryManager().get_history(
        current_user, role_type, limit=50, before=before,
    )
    return {"history": history}


@router.delete("/chat_history/{role_type}")
async def delete_chat_history(
    role_type: str,
    current_user: str = Depends(get_current_user),
):
    """删除聊天历史。"""
    await ChatHistoryManager().delete_history(current_user, role_type)
    return {"status": "ok"}
