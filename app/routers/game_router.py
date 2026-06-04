from fastapi import APIRouter, Depends, HTTPException
from app.dependencies import get_current_user
from app.game_service import GameService
from app.config import Settings


router = APIRouter(prefix="/game", tags=["game"])

# 依赖注入 game_service（使用单例 Settings）
def get_game_service():
    settings = Settings()   # pydantic-settings 每次实例化都会从环境变量/.env 读取相同配置
    return GameService(settings)

@router.get("/status")
async def get_status(role_type: str, user=Depends(get_current_user), service=Depends(get_game_service)):
    """获取养成状态（记忆扩容、动作等）"""
    return await service.get_unlock_info(user, role_type)

@router.get("/daily-tasks")
async def daily_tasks(role_type: str, user=Depends(get_current_user), service=Depends(get_game_service)):
    """获取每日任务列表"""
    return await service.get_daily_tasks(user, role_type)

@router.post("/daily-tasks/{task_id}/complete")
async def complete_daily_task(task_id: int, role_type: str, user=Depends(get_current_user), service=Depends(get_game_service)):
    """完成每日任务"""
    return await service.complete_daily_task(user, role_type, task_id)

@router.get("/achievements")
async def achievements(user=Depends(get_current_user), service=Depends(get_game_service)):
    """获取成就列表"""
    return await service.get_achievements(user)

@router.get("/skins")
async def skins(role_type: str, user=Depends(get_current_user), service=Depends(get_game_service)):
    """获取皮肤列表"""
    return await service.get_skins(user, role_type)

@router.post("/skins/equip")
async def equip_skin(role_type: str, skin_id: int, user=Depends(get_current_user), service=Depends(get_game_service)):
    """装备皮肤"""
    return await service.equip_skin(user, role_type, skin_id)