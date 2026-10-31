"""Authenticated specialist dispatch. Caller-supplied capabilities cannot escalate."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from orca.auth.middleware import get_current_user
from orca.auth.store import User
from orca.specialists.contracts import SpecialistError, TaskNode
from orca.specialists.orchestrator import Orchestrator

router = APIRouter(prefix="/api/specialists", tags=["specialists"])

_MEMBER = frozenset(
    {
        "research.read",
        "plan.write",
        "code.read",
        "data.read",
        "retrieval.read",
        "evidence.read",
        "security.read",
        "docs.write",
        "tool.hash",
        "mission.read",
    }
)


class TaskBody(BaseModel):
    task_id: str
    role: str
    payload: dict = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    irreversible: bool = False


class RunBody(BaseModel):
    tasks: list[TaskBody]
    capabilities: list[str] = Field(default_factory=list)


@router.post("/run")
async def run_specialists(body: RunBody, user: User = Depends(get_current_user)):
    requested = frozenset(body.capabilities) if body.capabilities else _MEMBER
    if not requested.issubset(_MEMBER):
        raise HTTPException(status_code=403, detail={"error": "privilege_escalation", "code": "privilege_escalation"})
    orch = Orchestrator(tenant_id=user.id, capabilities=requested)
    nodes = [
        TaskNode(
            task_id=item.task_id,
            role=item.role,
            payload=item.payload,
            depends_on=tuple(item.depends_on),
            capabilities=frozenset(),
            irreversible=item.irreversible,
        )
        for item in body.tasks
    ]
    # Empty task capabilities still require spec.capabilities ⊆ granted in invoke.
    try:
        return orch.run(nodes)
    except SpecialistError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": exc.code,
                "code": exc.code,
                "handlers_forcibly_stopped": getattr(exc, "handlers_forcibly_stopped", False),
                "handlers_still_running": getattr(exc, "still_running", []),
            },
        ) from exc
