"""
C02 Mission Execution -- authenticated REST API over the existing,
already-tested Phase 15 mission engine (`orca.mission.*`).

Scope of this increment (see docs/orneur/status/ORNEUR_C02_BACKEND_ENGINEERING_REPORT.md
for the full honest status): mission creation, plan transition,
permission request (operation request), approval/denial, mission
fetch/list (history), and a direct cancel. This is deliberately NOT
the full C02-01..C02-12 state surface -- live execution streaming
(SSE), tool-action detail views, evidence/output references, waiting-
for-input, and the CANCELLATION_REQUESTED/CANCELLED distinction are
explicitly NOT implemented here and are called out as open work.

Every domain decision (state legality, self-authorization, idempotency,
durable persistence) is made by the existing, already-tested
`orca.mission` modules -- this file's only job is: derive identity
from the server-verified session (never a client-supplied tenant/user
header), enforce per-mission ownership, and translate HTTP requests
into the existing store functions' calls.
"""
from __future__ import annotations

import secrets
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from orca.auth import get_current_user
from orca.auth.store import User
from orca.mission import mission_store, operation_store
from orca.mission.db import get_conn
from orca.mission.operation_store import (
    OperationConflictError,
    OperationNotFoundError,
    OperationStateError,
    SelfAuthorizationError,
)
from orca.mission.state_machine import MissionState, MissionStateError

router = APIRouter(prefix="/v1/missions", tags=["missions"])


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(12)}"


def _mission_conn():
    """FastAPI dependency: one mission-DB connection per request,
    always closed, matching this project's other per-request resource
    dependencies."""
    conn = get_conn()
    try:
        yield conn
    finally:
        conn.close()


def _get_owned_mission_or_404(conn, mission_id: str, user: User) -> dict:
    """The one ownership check every route in this file goes through.
    Looks the mission up by ID (never by a client-supplied owner
    field) and requires `owner_user_id == user.id` -- a mission that
    exists but belongs to someone else returns 404, not 403, so a
    caller cannot use this endpoint to enumerate other tenants'
    mission IDs (the response is identical whether the mission does
    not exist or simply isn't theirs)."""
    mission = mission_store.get_mission(conn, mission_id)
    if mission is None or mission["owner_user_id"] != user.id:
        raise HTTPException(status_code=404, detail="mission not found")
    return mission


class CreateMissionRequest(BaseModel):
    repository: str = Field(..., min_length=1, max_length=500)
    mode: Literal["ASSIST", "PROTOTYPE", "BUILD", "LAUNCH"]
    autonomy_level: Literal["L0", "L1", "L2", "L3", "L4"]
    branch: str | None = None


@router.post("", status_code=201)
async def create_mission(
    body: CreateMissionRequest,
    user: User = Depends(get_current_user),
    conn=Depends(_mission_conn),
):
    """Authenticated mission creation (C02 Variant A: Quiet Mission
    Brief). `owner_user_id` is always the server-verified caller --
    never taken from the request body, so a caller cannot create a
    mission "owned by" someone else."""
    mission_id = _new_id("mis")
    mission = mission_store.create_mission(
        conn,
        id=mission_id,
        repository=body.repository,
        mode=body.mode,
        autonomy_level=body.autonomy_level,
        owner_user_id=user.id,
        branch=body.branch,
    )
    return mission


@router.get("")
async def list_missions(
    user: User = Depends(get_current_user),
    conn=Depends(_mission_conn),
):
    """Minimal mission history (C02-12): every mission owned by the
    caller. Ownership-filtered in the query itself, not post-filtered
    in Python, so a caller's own list can never include another
    tenant's rows even transiently."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM missions WHERE owner_user_id = %s ORDER BY created_at DESC LIMIT 100",
            (user.id,),
        )
        rows = cur.fetchall()
    conn.commit()
    return {"missions": [dict(r) for r in rows]}


@router.get("/{mission_id}")
async def get_mission(
    mission_id: str,
    user: User = Depends(get_current_user),
    conn=Depends(_mission_conn),
):
    return _get_owned_mission_or_404(conn, mission_id, user)


@router.post("/{mission_id}/plan")
async def plan_mission(
    mission_id: str,
    user: User = Depends(get_current_user),
    conn=Depends(_mission_conn),
):
    """Transitions DRAFT -> PLANNING -> READY (C02 Variant B: pre-
    execution review becomes possible once READY). This increment
    does not generate a real plan; it only performs the legal state
    transition the real planning step would perform on success. No
    plan-generation call is made, and none is claimed to have been
    made."""
    _get_owned_mission_or_404(conn, mission_id, user)
    try:
        mission_store.transition_mission(conn, mission_id, MissionState.PLANNING)
        mission = mission_store.transition_mission(conn, mission_id, MissionState.READY)
    except MissionStateError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return mission


@router.post("/{mission_id}/cancel")
async def cancel_mission(
    mission_id: str,
    user: User = Depends(get_current_user),
    conn=Depends(_mission_conn),
):
    """Direct cancellation. KNOWN GAP (documented, not hidden): this
    does not yet distinguish a cancellation REQUEST from a confirmed,
    worker-terminated CANCELLED state -- see the engineering report's
    "Cancellation truth" section. Calling this marks the mission
    CANCELLED immediately; it does not itself verify that any running
    worker process has actually stopped."""
    _get_owned_mission_or_404(conn, mission_id, user)
    try:
        mission = mission_store.transition_mission(conn, mission_id, MissionState.CANCELLED)
    except MissionStateError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return mission


class RequestOperationRequest(BaseModel):
    kind: str = Field(..., min_length=1, max_length=200)
    target: str = ""
    parameters: dict | None = None
    idempotency_key: str = Field(..., min_length=1, max_length=200)


@router.post("/{mission_id}/operations", status_code=201)
async def request_operation(
    mission_id: str,
    body: RequestOperationRequest,
    user: User = Depends(get_current_user),
    conn=Depends(_mission_conn),
):
    """Permission request (C02-01). `requested_by` is always the
    server-verified caller. Idempotent: a retried request with the
    same `idempotency_key` and the same material parameters returns
    the existing operation rather than creating a duplicate
    side-effecting request (a 409 is raised instead if the same key
    was reused with DIFFERENT parameters, per
    `orca.mission.operation_store`'s own existing conflict check)."""
    _get_owned_mission_or_404(conn, mission_id, user)
    op_id = _new_id("op")
    try:
        operation, created = operation_store.request_operation(
            conn,
            id=op_id,
            idempotency_key=body.idempotency_key,
            kind=body.kind,
            requested_by=user.id,
            mission_id=mission_id,
            target=body.target,
            parameters=body.parameters,
        )
    except OperationConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return {"operation": operation, "created": created}


@router.get("/{mission_id}/operations/{operation_id}")
async def get_operation(
    mission_id: str,
    operation_id: str,
    user: User = Depends(get_current_user),
    conn=Depends(_mission_conn),
):
    _get_owned_mission_or_404(conn, mission_id, user)
    operation = operation_store.get_operation(conn, operation_id)
    if operation is None or operation["mission_id"] != mission_id:
        raise HTTPException(status_code=404, detail="operation not found")
    return operation


class ApprovalDecisionRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=2000)
    arguments: dict | None = None


@router.post("/{mission_id}/operations/{operation_id}/approve")
async def approve_operation(
    mission_id: str,
    operation_id: str,
    body: ApprovalDecisionRequest,
    user: User = Depends(get_current_user),
    conn=Depends(_mission_conn),
):
    """Approval decision (C02-02). The mission itself may belong to
    the approver (an operator approving their own mission's tool
    calls is the expected flow) -- what is REJECTED, by
    `operation_store.authorize_operation()` itself, is the SAME
    identity having both REQUESTED and approved this specific
    operation (self-authorization), never bypassed here."""
    mission = _get_owned_mission_or_404(conn, mission_id, user)
    try:
        operation, allowed = operation_store.authorize_operation(
            conn,
            operation_id,
            tenant_id=mission.get("workspace_id") or mission["owner_user_id"],
            approved_by=user.id,
            reason=body.reason,
            arguments=body.arguments,
        )
    except OperationNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except SelfAuthorizationError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except OperationStateError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return {"operation": operation, "allowed": allowed}


@router.post("/{mission_id}/operations/{operation_id}/deny")
async def deny_operation(
    mission_id: str,
    operation_id: str,
    user: User = Depends(get_current_user),
    conn=Depends(_mission_conn),
):
    """Denial (C02-02, the rejecting path). Implemented as a direct
    cancel of the REQUESTED operation -- there is no separate "denied"
    terminal status in the existing operation state machine
    (REQUESTED -> AUTHORIZED -> STARTED -> SUCCEEDED|FAILED, or
    REQUESTED/AUTHORIZED -> CANCELLED); a denial is represented as
    CANCELLED with the approval decision (if the caller wants one
    recorded) made via `/approve` returning `allowed=False` instead.
    This endpoint is the "I am not even going to let godmode decide"
    fast-reject path."""
    _get_owned_mission_or_404(conn, mission_id, user)
    operation = operation_store.get_operation(conn, operation_id)
    if operation is None or operation["mission_id"] != mission_id:
        raise HTTPException(status_code=404, detail="operation not found")
    try:
        operation = operation_store.cancel_operation(conn, operation_id)
    except OperationStateError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return operation
