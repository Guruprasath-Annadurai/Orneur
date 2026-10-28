"""HTTP inference. Owner is the session user. Unavailable providers stay unavailable.

Frozen frontend chat remains `/api/chat` with its existing `session_id`.
These routes keep the same response fields and add `session_id` so two
conversations of one user cannot share a transcript.
"""

from __future__ import annotations

import asyncio
import json
import threading

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from orca.auth.middleware import get_current_user
from orca.auth.store import User
from orca.config import CONFIG
from orca.serve import ratelimit
from orca.serve.inference import InferenceError, complete, history, stream_via_gateway

router = APIRouter(prefix="/api/inference", tags=["inference"])

_STATUS = {
    "unauthenticated": 401,
    "session_required": 400,
    "session_not_found": 404,
    "provider_unavailable": 503,
    "provider_timeout": 504,
    "paid_backend_refused": 403,
    "quota_exceeded": 429,
    "model_access_denied": 403,
    "content_refused": 403,
    "native_identity_refused": 409,
    "prompt_refused": 400,
    "model_refused": 400,
    "unknown_model": 403,
    "variant_mismatch": 403,
    "quota_unavailable": 503,
    "session_busy": 409,
}


class CompleteBody(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    model: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]{1,64}$")
    model_variant: str | None = Field(default=None, max_length=32)


def _http(exc: InferenceError) -> HTTPException:
    return HTTPException(status_code=_STATUS.get(exc.code, 409), detail={"error": exc.code, "code": exc.code})


@router.post("/complete")
async def inference_complete(body: CompleteBody, request: Request, user: User = Depends(get_current_user)):
    ratelimit.enforce(request, ratelimit.CHAT_ANY, extra_key="inference_complete")
    try:
        return await asyncio.to_thread(
            complete,
            user=user,
            message=body.message,
            model=body.model,
            host=CONFIG.ollama.host,
            session_id=body.session_id,
            model_variant=body.model_variant,
        )
    except InferenceError as exc:
        raise _http(exc) from exc


@router.post("/stream")
async def inference_stream(body: CompleteBody, request: Request, user: User = Depends(get_current_user)):
    ratelimit.enforce(request, ratelimit.CHAT_ANY, extra_key="inference_stream")
    cancel = threading.Event()

    async def events():
        try:
            async for item in stream_via_gateway(
                user=user,
                message=body.message,
                model=body.model,
                host=CONFIG.ollama.host,
                session_id=body.session_id,
                model_variant=body.model_variant,
                cancel=cancel,
            ):
                yield f"data: {json.dumps(item)}\n\n"
                if await request.is_disconnected():
                    cancel.set()
                    yield f"data: {json.dumps({'type': 'cancelled', 'reason': 'client_disconnect', 'handlers_forcibly_stopped': False})}\n\n"
                    return
        except InferenceError as exc:
            yield f"data: {json.dumps({'type': 'error', 'code': exc.code, 'error': exc.code})}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@router.get("/history")
async def inference_history(
    request: Request,
    session_id: str = Query(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]{1,64}$"),
    user: User = Depends(get_current_user),
):
    ratelimit.enforce(request, ratelimit.CHAT_ANY, extra_key="inference_history")
    try:
        messages = await asyncio.to_thread(history, user=user, session_id=session_id)
        return {"user_id": user.id, "session_id": session_id, "messages": messages}
    except InferenceError as exc:
        raise _http(exc) from exc
