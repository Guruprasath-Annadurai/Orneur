"""HTTP untrusted execution. Off unless development flag is set. Auth required."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from orca.auth.middleware import get_current_user
from orca.auth.store import User
from orca.serve import ratelimit
from orca.code.untrusted import UntrustedError, execute, execution_enabled, get_job, list_jobs

router = APIRouter(prefix="/api/untrusted", tags=["untrusted"])

_STATUS = {
    "unauthenticated": 401,
    "access_denied": 403,
    "isolation_unavailable": 503,
    "image_unavailable": 503,
    "caller_flags_refused": 400,
    "concurrency_refused": 429,
}


class ExecuteBody(BaseModel):
    source: str = Field(min_length=1, max_length=65536)
    task_id: str = Field(default="untrusted-dev", min_length=1, max_length=64)
    privileged: bool = False
    image: str | None = None
    network: str | None = None


@router.post("/execute")
async def untrusted_execute(body: ExecuteBody, request: Request, user: User = Depends(get_current_user)):
    ratelimit.enforce(request, ratelimit.CODE_RUN, extra_key="untrusted_execute")
    if not execution_enabled():
        raise HTTPException(
            status_code=403,
            detail={"error": "capability_disabled", "code": "capability_disabled"},
        )
    try:
        return execute(
            body.source,
            user=user,
            task_id=body.task_id,
            privileged=body.privileged,
            image=body.image,
            network=body.network,
        )
    except UntrustedError as exc:
        raise HTTPException(
            status_code=_STATUS.get(exc.code, 409),
            detail={"error": exc.code, "code": exc.code, **exc.extra},
        ) from exc


@router.get("/jobs")
async def untrusted_jobs(request: Request, user: User = Depends(get_current_user)):
    ratelimit.enforce(request, ratelimit.CODE_RUN, extra_key="untrusted_jobs")
    if not execution_enabled():
        raise HTTPException(status_code=403, detail={"error": "capability_disabled", "code": "capability_disabled"})
    return {"user_id": user.id, "jobs": list_jobs(user=user)}


@router.get("/jobs/{job_id}")
async def untrusted_job(job_id: str, request: Request, user: User = Depends(get_current_user)):
    ratelimit.enforce(request, ratelimit.CODE_RUN, extra_key="untrusted_job")
    if not execution_enabled():
        raise HTTPException(status_code=403, detail={"error": "capability_disabled", "code": "capability_disabled"})
    try:
        return get_job(user=user, job_id=job_id)
    except UntrustedError as exc:
        raise HTTPException(
            status_code=_STATUS.get(exc.code, 409),
            detail={"error": exc.code, "code": exc.code},
        ) from exc
