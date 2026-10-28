"""HTTP boundary. The caller does not choose the owner."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from orca.auth.middleware import get_current_user
from orca.auth.store import User
from orca.sovereign_mission.service import MissionError, SovereignMission

router = APIRouter(prefix="/api/sovereign", tags=["sovereign-mission"])
_missions: SovereignMission | None = None


def _service() -> SovereignMission:
    global _missions
    if _missions is None:
        _missions = SovereignMission()
    return _missions

_STATUS = {
    "unauthenticated": 401,
    "access_denied": 403,
    "mission_not_found": 404,
    "step_not_found": 404,
}


class ObjectiveBody(BaseModel):
    objective: str = Field(min_length=1, max_length=500)


class PlanBody(BaseModel):
    steps: list[dict]


class ApprovalBody(BaseModel):
    step_id: str
    ttl_seconds: int = Field(ge=1, le=120)


class DispatchBody(BaseModel):
    step_id: str


def _call(action):
    try:
        return action()
    except MissionError as exc:
        raise HTTPException(status_code=_STATUS.get(exc.code, 409), detail={"error": exc.code, "code": exc.code}) from exc


@router.post("/missions")
async def create_mission(body: ObjectiveBody, user: User = Depends(get_current_user)):
    return _call(lambda: _service().create(user, body.objective))


@router.get("/missions/{mission_id}")
async def read_mission(mission_id: str, user: User = Depends(get_current_user)):
    return _call(lambda: _service().get(user, mission_id))


@router.post("/missions/{mission_id}/plan")
async def save_plan(mission_id: str, body: PlanBody, user: User = Depends(get_current_user)):
    return _call(lambda: _service().save_plan(user, mission_id, body.steps))


@router.post("/missions/{mission_id}/approval-request")
async def request_approval(mission_id: str, user: User = Depends(get_current_user)):
    return _call(lambda: _service().request_approval(user, mission_id))


@router.post("/missions/{mission_id}/approvals")
async def approve(mission_id: str, body: ApprovalBody, user: User = Depends(get_current_user)):
    return _call(lambda: _service().approve(user, mission_id, body.step_id, ttl_seconds=body.ttl_seconds))


@router.post("/missions/{mission_id}/dispatch")
async def dispatch(mission_id: str, body: DispatchBody, user: User = Depends(get_current_user)):
    return _call(lambda: _service().dispatch(user, mission_id, body.step_id))


@router.post("/missions/{mission_id}/pause")
async def pause(mission_id: str, user: User = Depends(get_current_user)):
    return _call(lambda: _service().pause(user, mission_id))


@router.post("/missions/{mission_id}/resume")
async def resume(mission_id: str, user: User = Depends(get_current_user)):
    return _call(lambda: _service().resume(user, mission_id))


@router.post("/missions/{mission_id}/cancel")
async def cancel(mission_id: str, user: User = Depends(get_current_user)):
    return _call(lambda: _service().request_cancel(user, mission_id))


@router.post("/missions/{mission_id}/revoke")
async def revoke(mission_id: str, user: User = Depends(get_current_user)):
    return _call(lambda: _service().revoke(user, mission_id))


@router.post("/missions/{mission_id}/recover")
async def recover(mission_id: str, user: User = Depends(get_current_user)):
    return _call(lambda: _service().recover(user, mission_id))


@router.get("/missions/{mission_id}/evidence")
async def evidence(mission_id: str, user: User = Depends(get_current_user)):
    return _call(lambda: _service().evidence(user, mission_id))


@router.get("/missions/{mission_id}/result")
async def result(mission_id: str, user: User = Depends(get_current_user)):
    return _call(lambda: _service().reported(user, mission_id))
