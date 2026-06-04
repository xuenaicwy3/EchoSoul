from fastapi import APIRouter, Depends
from app.dependencies import get_current_user
from app.affective_memory_service import AffectiveMemoryService
from app.config import Settings

router = APIRouter(prefix="/memory", tags=["affective_memory"])

def get_service():
    return AffectiveMemoryService(Settings())

@router.get("/facts/{role_type}")
async def get_facts(role_type: str, user=Depends(get_current_user), svc=Depends(get_service)):
    return await svc.get_facts(user, role_type)

@router.get("/emotion_trend/{role_type}")
async def emotion_trend(role_type: str, user=Depends(get_current_user), svc=Depends(get_service)):
    return await svc.get_emotion_trend(user, role_type)

@router.get("/milestones/{role_type}")
async def milestones(role_type: str, user=Depends(get_current_user), svc=Depends(get_service)):
    return await svc.get_milestones(user, role_type)