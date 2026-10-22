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


class PlanMissionRequest(BaseModel):
    steps: list[str] = Field(..., min_length=1)


@router.post("/{mission_id}/plan")
async def plan_mission(
    mission_id: str,
    body: PlanMissionRequest,
    user: User = Depends(get_current_user),
    conn=Depends(_mission_conn),
):
    """Transitions DRAFT -> PLANNING -> READY (C02 Variant B: pre-
    execution review becomes possible once READY) ONLY after
    persisting the caller-supplied plan as real `mission_steps` rows.

    AUDIT-C02-P1-01 ("planning truth") fix: this endpoint previously
    performed the state transition with no plan content at all --
    a mission could reach READY, the state pre-execution review
    depends on, with nothing to actually review. This codebase has no
    automatic plan-generation capability (no LLM-driven planner is
    wired up anywhere) -- "real planning integration" in this
    increment means persisting and validating a genuine, non-empty,
    ordered plan the caller supplies, not fabricating one. `steps`
    must be non-empty (enforced by Pydantic `min_length=1` before this
    handler even runs); if it is empty, the request is rejected with
    422 and the mission never leaves DRAFT -- no silent READY with
    no plan."""
    _get_owned_mission_or_404(conn, mission_id, user)
    try:
        mission_store.transition_mission(conn, mission_id, MissionState.PLANNING)
        # Persist the plan WHILE still in PLANNING, before ever
        # reaching READY -- if persisting steps fails for any reason,
        # the mission is left in PLANNING (visibly "stuck," honestly
        # reflecting that planning did not complete), never silently
        # advanced to READY with no real plan behind it.
        mission_store.create_mission_steps(conn, mission_id, body.steps)
        mission = mission_store.transition_mission(conn, mission_id, MissionState.READY)
    except MissionStateError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return mission


@router.get("/{mission_id}/steps")
async def get_mission_steps(
    mission_id: str,
    user: User = Depends(get_current_user),
    conn=Depends(_mission_conn),
):
    _get_owned_mission_or_404(conn, mission_id, user)
    return {"steps": list(mission_store.list_mission_steps(conn, mission_id))}


_LIVE_WORKER_STATES = frozenset({
    MissionState.RUNNING, MissionState.WAITING_TOOL, MissionState.WAITING_EXTERNAL_EVENT,
    MissionState.WAITING_APPROVAL, MissionState.PAUSED_USER, MissionState.PAUSED_WINDOW_REACHED,
    MissionState.BLOCKED,
})

# The ONLY states from which a direct-to-CANCELLED /cancel call is
# legitimate: nothing is running yet, so there is nothing to confirm
# terminated. Anything else -- including CANCELLATION_REQUESTED itself
# -- must be rejected here, not silently treated as "no live worker."
# (A bug caught in this increment's own tests: using `not in
# _LIVE_WORKER_STATES` as the direct-cancel condition instead of this
# explicit allowlist let a SECOND /cancel call on an already-
# CANCELLATION_REQUESTED mission self-confirm straight to CANCELLED,
# completely bypassing /confirm-cancelled.)
_PRE_RUN_STATES = frozenset({MissionState.DRAFT, MissionState.PLANNING, MissionState.READY})


@router.post("/{mission_id}/cancel")
async def cancel_mission(
    mission_id: str,
    user: User = Depends(get_current_user),
    conn=Depends(_mission_conn),
):
    """C02-08/C02-09 (cancellation request / confirmed cancellation).

    AUDIT-C02-P0-03 fix: previously transitioned straight to CANCELLED
    even from RUNNING -- marking a mission cancelled with no check
    that any live worker process had actually stopped (a false
    'success' report). `orca.mission.state_machine` now makes
    CANCELLATION_REQUESTED a distinct, persisted state: any mission
    that MIGHT have a live worker (RUNNING or any WAITING_*/PAUSED_*/
    BLOCKED state) moves to CANCELLATION_REQUESTED here, never
    directly to CANCELLED. DRAFT/PLANNING/READY (nothing running yet)
    still go straight to CANCELLED, since there is nothing to confirm
    terminated.

    This endpoint does NOT itself perform worker termination or
    reconciliation -- that mechanism does not exist in this codebase
    yet (orca.mission.executor/container_executor/sandbox_executor are
    not wired to this API layer in this increment). Confirming
    CANCELLATION_REQUESTED -> CANCELLED is `/confirm-cancelled` below,
    and until something actually drives that confirmation, a mission
    correctly stays in CANCELLATION_REQUESTED rather than being
    reported as cancelled."""
    mission = _get_owned_mission_or_404(conn, mission_id, user)
    current_state = MissionState(mission["state"])
    if current_state in _PRE_RUN_STATES:
        target = MissionState.CANCELLED
    elif current_state in _LIVE_WORKER_STATES:
        target = MissionState.CANCELLATION_REQUESTED
    else:
        # CANCELLATION_REQUESTED itself, or any terminal state: there
        # is no legitimate "/cancel again" action from here. Resolve
        # via /confirm-cancelled instead, or accept the existing
        # terminal outcome.
        raise HTTPException(
            status_code=409,
            detail=f"cannot cancel a mission in state {current_state.value} -- "
                   f"use /confirm-cancelled if it is already CANCELLATION_REQUESTED",
        )
    try:
        mission = mission_store.transition_mission(conn, mission_id, target)
    except MissionStateError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return mission


class ConfirmCancelledRequest(BaseModel):
    termination_confirmed: bool


@router.post("/{mission_id}/confirm-cancelled")
async def confirm_cancelled(
    mission_id: str,
    body: ConfirmCancelledRequest,
    user: User = Depends(get_current_user),
    conn=Depends(_mission_conn),
):
    """Resolves a CANCELLATION_REQUESTED mission to its confirmed
    outcome: CANCELLED if `termination_confirmed=True`, or FAILED
    (fail-closed, never a silent CANCELLED) if `termination_confirmed
    =False` -- e.g. a reconciliation process determined the worker did
    not cleanly stop.

    HONEST SCOPE NOTE: this endpoint is the explicit confirmation
    hook the directive's "cancellation truth" requirement calls for.
    It does not itself verify worker termination -- there is no
    automated reconciliation loop in this codebase wired to missions
    yet. Until one exists, callers (an operator, or a future
    reconciliation job) must supply `termination_confirmed` from a
    real, out-of-band check; this endpoint refuses to invent that
    answer itself."""
    mission = _get_owned_mission_or_404(conn, mission_id, user)
    target = MissionState.CANCELLED if body.termination_confirmed else MissionState.FAILED
    try:
        mission = mission_store.transition_mission(conn, mission_id, target)
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
    `orca.mission.operation_store`'s own existing conflict check).

    AUDIT-C02-P0-01 fix: `operations.idempotency_key` is a GLOBALLY
    unique column in the existing schema (`orca/mission/schema.py`),
    not scoped to `(mission_id, idempotency_key)` -- deliberately left
    unchanged here (preserving existing schema/behavior other callers
    may depend on). `operation_store.request_operation()` itself has
    no notion of "mission" ownership for its idempotency check: if the
    SAME key (and matching kind/target/parameters fingerprint) was
    previously used under a DIFFERENT mission, it returns THAT
    mission's existing operation row as if it were a successful retry
    -- independently reproduced before this fix. This endpoint now
    verifies the returned operation actually belongs to the URL's
    `mission_id` before treating it as a legitimate idempotent retry;
    a cross-mission collision is reported as a conflict, never
    silently returned."""
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
    if operation["mission_id"] != mission_id:
        raise HTTPException(
            status_code=409,
            detail=(
                "idempotency_key is already in use by an operation under a different mission -- "
                "idempotency keys must be unique per caller across all missions, not just within one"
            ),
        )
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
    operation (self-authorization), never bypassed here.

    AUDIT-C02-P0-02 fix: this endpoint previously called
    `authorize_operation(operation_id, ...)` after checking only that
    the CALLER owns `mission_id` (the URL's mission) -- it never
    verified `operation_id` itself actually belongs to that mission.
    An operation ID is an unguessable token, but a caller who learned
    one belonging to a DIFFERENT mission (e.g. via the P0-01 cross-
    mission idempotency collision, now closed, or any other channel)
    could have approved/denied an operation outside any mission they
    actually control. This endpoint now performs the same
    operation-belongs-to-this-mission check `get_operation()` and
    `deny_operation()` already perform, BEFORE calling into the
    authority engine at all."""
    mission = _get_owned_mission_or_404(conn, mission_id, user)
    existing_operation = operation_store.get_operation(conn, operation_id)
    if existing_operation is None or existing_operation["mission_id"] != mission_id:
        raise HTTPException(status_code=404, detail="operation not found")
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
