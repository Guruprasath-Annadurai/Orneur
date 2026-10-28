"""HTTP inference. Owner is the session user. Unavailable providers stay unavailable."""

from __future__ import annotations

import json
import threading

from fastapi import APIRouter, Depends, HTTPException, Request
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
    "provider_unavailable": 503,
    "provider_timeout": 504,
    "paid_backend_refused": 403,
}


class CompleteBody(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    model: str = Field(min_length=1, max_length=128)


def _http(exc: InferenceError) -> HTTPException:
    return HTTPException(status_code=_STATUS.get(exc.code, 409), detail={"error": exc.code, "code": exc.code})


@router.post("/complete")
async def inference_complete(body: CompleteBody, request: Request, user: User = Depends(get_current_user)):
    ratelimit.enforce(request, ratelimit.CHAT_ANY, extra_key="inference_complete")
    try:
        return complete(user=user, message=body.message, model=body.model, host=CONFIG.ollama.host)
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
async def inference_history(request: Request, user: User = Depends(get_current_user)):
    ratelimit.enforce(request, ratelimit.CHAT_ANY, extra_key="inference_history")
    return {"user_id": user.id, "messages": history(user.id)}
