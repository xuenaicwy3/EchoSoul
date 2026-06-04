from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.dependencies import get_current_user
from app.story_service import StoryService
from app.config import Settings

router = APIRouter(prefix="/story", tags=["story"])

def get_story_service():
    return StoryService(Settings())

class ContinueRequest(BaseModel):
    choice_id: int

class StartStoryRequest(BaseModel):
    role_type: str = "日系少女动漫型"
    title: str
    starter_text: str
    options: list = []   # 新增：预设的选项列表

class ProgressRequest(BaseModel):
    type: str                      # "choice", "free_text", "auto"
    choice_id: Optional[int] = None
    free_text: Optional[str] = None
    auto_hint: Optional[str] = None  # 用户偏好，如“偏向探索”


@router.get("/starters")
async def get_starters(category: Optional[str] = None, user=Depends(get_current_user), svc=Depends(get_story_service)):
    return await svc.get_starters(category)

@router.post("/start")
async def start_story(req: StartStoryRequest, user=Depends(get_current_user), svc=Depends(get_story_service)):
    result = await svc.start_story(user, req.role_type, req.title, req.starter_text, req.options)
    return result

@router.post("/{story_id}/progress")
async def progress_story(story_id: int, req: ProgressRequest, user=Depends(get_current_user), svc=Depends(get_story_service)):
    result = await svc.progress_story(
        story_id=story_id,
        user_id=user,
        progress_type=req.type,
        choice_id=req.choice_id,
        free_text=req.free_text,
        auto_hint=req.auto_hint
    )
    if result is None:
        raise HTTPException(status_code=400, detail="无法推进故事，请检查参数或故事状态")
    return result


@router.get("/{story_id}")
async def get_story(story_id: int, user=Depends(get_current_user), svc=Depends(get_story_service)):
    nodes = await svc.get_story_nodes(story_id, user)
    if nodes is None:
        raise HTTPException(status_code=404, detail="故事不存在或无权访问")
    return {"nodes": nodes}

@router.post("/{story_id}/continue")
async def continue_story(story_id: int, req: ContinueRequest, user=Depends(get_current_user), svc=Depends(get_story_service)):
    result = await svc.continue_story(story_id, user, req.choice_id)
    if not result:
        raise HTTPException(status_code=400, detail="无法继续，可能故事已结束或无权操作")
    return result

@router.put("/{story_id}/archive")
async def archive_story(story_id: int, user=Depends(get_current_user), svc=Depends(get_story_service)):
    success = await svc.archive_story(story_id, user)
    if not success:
        raise HTTPException(status_code=404, detail="故事不存在或无权操作")
    return {"message": "已存档"}

@router.delete("/{story_id}")
async def delete_story(story_id: int, user=Depends(get_current_user), svc=Depends(get_story_service)):
    success = await svc.delete_story(story_id, user)
    if not success:
        raise HTTPException(status_code=404, detail="故事不存在或无权操作")
    return {"message": "已删除"}