"""Authenticated local inference through the Ollama adapter.

Conversation truth is the canonical per-session transcript
(`orca.serve.conversations`) plus Redis session_store when enabled.
This module does not keep a second user-global history.

Does not impersonate GENESIS, NOVUS, or AETERNUM. Serving policy
(quota, entitlement, moderation, DLP, spending) runs before every
provider call.
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time
import uuid

from orca.auth.store import check_quota, claim_session, increment_usage, model_access_allowed
from orca.gateway.contracts import InferenceRequest
from orca.gateway.errors import DeploymentUnavailableError, GenerationTimeoutError, RequestCancelledError
from orca.gateway.ollama_runtime import OllamaRuntime
from orca.rse.imp1.locks import spending_authorized
from orca.serve import conversations, dlp, session_store
from orca.serve.availability import probe_ollama
from orca.serve.model_identity import model_identity
from orca.serve.moderation import check_input
from orca.serve.usage import NATIVE_FAMILIES, PAID_BACKENDS, record_usage

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_MAX_CONTEXT = 40
_NATIVE_PREFIXES = ("genesis", "novus", "aeternum", "orneur-genesis", "orneur-novus", "orneur-aeternum")
_TURN_LOCKS: dict[str, threading.Lock] = {}
_TURN_LOCKS_GUARD = threading.Lock()


class InferenceError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _user_id(user: object) -> str:
    if isinstance(user, (str, bytes, bytearray, dict)):
        raise InferenceError("unauthenticated")
    uid = getattr(user, "id", None)
    if not isinstance(uid, str) or not uid.strip():
        raise InferenceError("unauthenticated")
    return uid


def _native_refused(name: str) -> bool:
    n = (name or "").strip().lower()
    if n in NATIVE_FAMILIES:
        return True
    return any(n == p or n.startswith(p + ":") or n.startswith(p + "-") for p in _NATIVE_PREFIXES)


def _session_id(session_id: str | None) -> str:
    if not isinstance(session_id, str) or not _SESSION_ID_RE.fullmatch(session_id):
        raise InferenceError("session_required")
    return session_id


def bind_session(*, user_id: str, session_id: str) -> str:
    sid = _session_id(session_id)
    if not claim_session(sid, user_id):
        raise InferenceError("session_not_found")
    return sid


def authorize_serving(*, user: object, message: str, model: str, model_variant: str = "nano") -> str:
    uid = _user_id(user)
    if not isinstance(message, str) or not message.strip():
        raise InferenceError("prompt_refused")
    if not isinstance(model, str) or not model.strip():
        raise InferenceError("model_refused")
    if _native_refused(model) or _native_refused(model_variant):
        raise InferenceError("native_identity_refused")
    variant = (model_variant or "nano").removeprefix("orca-")
    allowed, _used, _limit = check_quota(uid, getattr(user, "tier", "free") or "free", "message")
    if not allowed:
        raise InferenceError("quota_exceeded")
    ok, _reason = model_access_allowed(user, variant)
    if not ok:
        raise InferenceError("model_access_denied")
    if check_input(message).action == "block":
        raise InferenceError("content_refused")
    lowered = model.strip().lower()
    if any(lowered.startswith(p) for p in ("gpt-", "claude", "gemini", "openai", "anthropic")):
        refuse_paid(backend="openai")
    if not spending_authorized() and lowered in PAID_BACKENDS:
        refuse_paid(backend=lowered)
    return uid


def _session_lock(session_id: str) -> threading.Lock:
    with _TURN_LOCKS_GUARD:
        lock = _TURN_LOCKS.get(session_id)
        if lock is None:
            lock = threading.Lock()
            _TURN_LOCKS[session_id] = lock
        return lock


def _safe_text(text: str) -> str:
    return dlp.scan_output(text or "")["safe_text"]


def _session_messages(session_id: str) -> list[dict]:
    body = conversations.transcript(session_id, limit=1000, offset=0)
    total = int(body.get("total") or 0)
    rows = body.get("messages") or []
    if total > len(rows):
        offset = max(0, total - _MAX_CONTEXT)
        rows = conversations.transcript(session_id, limit=_MAX_CONTEXT, offset=offset).get("messages") or []
    return [{"role": row["role"], "content": row["content"]} for row in rows[-_MAX_CONTEXT:]]


def history(*, user: object, session_id: str) -> list[dict]:
    uid = _user_id(user)
    sid = bind_session(user_id=uid, session_id=session_id)
    return _session_messages(sid)


def reset_for_tests() -> None:
    with _TURN_LOCKS_GUARD:
        _TURN_LOCKS.clear()


def _prompt_with_session(session_id: str, message: str) -> str:
    parts = [f"{row['role']}: {row['content']}" for row in _session_messages(session_id)]
    parts.append(f"user: {message}")
    return "\n".join(parts)


def _messages_with_session(session_id: str, message: str) -> list[dict]:
    return [*_session_messages(session_id), {"role": "user", "content": message}]


def _identity(served: str) -> dict:
    return model_identity(
        requested_variant=None,
        served_tier=None,
        served_model=served,
        backend="ollama",
        data_left_infrastructure=False,
    )


def _persist(*, user_id: str, session_id: str, message: str, text: str, identity: dict, model_variant: str) -> str:
    safe = _safe_text(text)
    conversations.append(session_id, "user", message)
    conversations.append(session_id, "assistant", safe, meta={"model_identity": identity})
    session_store.save_session_state(session_id, model_variant or "nano", _session_messages(session_id))
    session_store.touch_session(session_id)
    increment_usage(user_id, "message")
    return safe


def complete(
    *,
    user: object,
    message: str,
    model: str,
    host: str,
    session_id: str,
    model_variant: str = "nano",
    transport_generate=None,
    synthetic_provider: bool = False,
    timeout_s: float = 30.0,
) -> dict:
    uid = authorize_serving(user=user, message=message, model=model, model_variant=model_variant)
    sid = bind_session(user_id=uid, session_id=session_id)
    with _session_lock(sid):
        return _complete_locked(
            uid=uid,
            sid=sid,
            message=message,
            model=model,
            host=host,
            model_variant=model_variant,
            transport_generate=transport_generate,
            synthetic_provider=synthetic_provider,
            timeout_s=timeout_s,
        )


def _complete_locked(
    *,
    uid: str,
    sid: str,
    message: str,
    model: str,
    host: str,
    model_variant: str,
    transport_generate,
    synthetic_provider: bool,
    timeout_s: float,
) -> dict:
    probe = probe_ollama(host=host, timeout_s=2.0)
    if probe["status"] != "reachable" and transport_generate is None:
        raise InferenceError("provider_unavailable")
    prompt = _prompt_with_session(sid, message.strip())
    t0 = time.monotonic()
    if transport_generate is not None:
        data = transport_generate(host, model, prompt)
    else:
        import httpx

        try:
            response = httpx.post(
                host.rstrip("/") + "/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"num_predict": 64, "temperature": 0},
                },
                timeout=timeout_s,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.TimeoutException as exc:
            raise InferenceError("provider_timeout") from exc
        except Exception as exc:
            raise InferenceError("provider_unavailable") from exc
    text = data.get("response") or ""
    served = data.get("model") or model
    if _native_refused(served):
        raise InferenceError("native_identity_refused")
    latency_ms = (time.monotonic() - t0) * 1000
    tokens_in = int(data.get("prompt_eval_count") or 0)
    tokens_out = int(data.get("eval_count") or 0)
    identity = _identity(served)
    record_usage(user_id=uid, model=served, backend="ollama", tokens_in=tokens_in, tokens_out=tokens_out)
    safe = _persist(user_id=uid, session_id=sid, message=message.strip(), text=text, identity=identity, model_variant=model_variant)
    return {
        "text": safe,
        "model": served,
        "backend": "ollama",
        "identity": identity,
        "latency_ms": round(latency_ms, 1),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "live": not synthetic_provider and probe["status"] == "reachable",
        "synthetic_provider": bool(synthetic_provider),
        "native_family": None,
        "path": "/api/generate",
        "session_id": sid,
        "request_id": uuid.uuid4().hex,
    }


def runtime_for(host: str, timeout_s: float = 30.0) -> OllamaRuntime:
    return OllamaRuntime(host=host, deployment_id="ollama-local", timeout_s=timeout_s)


def stream_complete(
    *,
    user: object,
    message: str,
    model: str,
    host: str,
    session_id: str,
    model_variant: str = "nano",
    transport_stream=None,
    cancel: threading.Event | None = None,
    synthetic_provider: bool = False,
    timeout_s: float = 30.0,
) -> dict:
    uid = authorize_serving(user=user, message=message, model=model, model_variant=model_variant)
    sid = bind_session(user_id=uid, session_id=session_id)
    with _session_lock(sid):
        return _stream_complete_locked(
            uid=uid,
            sid=sid,
            message=message,
            model=model,
            host=host,
            model_variant=model_variant,
            transport_stream=transport_stream,
            cancel=cancel,
            synthetic_provider=synthetic_provider,
            timeout_s=timeout_s,
        )


def _stream_complete_locked(
    *,
    uid: str,
    sid: str,
    message: str,
    model: str,
    host: str,
    model_variant: str,
    transport_stream,
    cancel: threading.Event | None,
    synthetic_provider: bool,
    timeout_s: float,
) -> dict:
    probe = probe_ollama(host=host, timeout_s=2.0)
    if probe["status"] != "reachable" and transport_stream is None:
        raise InferenceError("provider_unavailable")
    chunks: list[str] = []
    cancelled = False
    tokens_in = 0
    tokens_out = 0
    served = model
    messages = _messages_with_session(sid, message.strip())
    if transport_stream is not None:
        for delta in transport_stream(host, model, message.strip()):
            if cancel is not None and cancel.is_set():
                cancelled = True
                break
            if delta:
                chunks.append(_safe_text(delta))
    else:
        import httpx

        try:
            with httpx.stream(
                "POST",
                host.rstrip("/") + "/api/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "stream": True,
                    "options": {"num_predict": 64, "temperature": 0},
                },
                timeout=timeout_s,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if cancel is not None and cancel.is_set():
                        cancelled = True
                        break
                    if not line:
                        continue
                    payload = json.loads(line)
                    served = payload.get("model") or served
                    piece = (payload.get("message") or {}).get("content") or payload.get("response") or ""
                    if piece:
                        chunks.append(_safe_text(piece))
                    if payload.get("done"):
                        tokens_in = int(payload.get("prompt_eval_count") or 0)
                        tokens_out = int(payload.get("eval_count") or 0)
                        break
        except httpx.TimeoutException as exc:
            raise InferenceError("provider_timeout") from exc
        except Exception as exc:
            raise InferenceError("provider_unavailable") from exc
    if _native_refused(served):
        raise InferenceError("native_identity_refused")
    text = "".join(chunks)
    identity = _identity(served)
    if not cancelled:
        record_usage(user_id=uid, model=served, backend="ollama", tokens_in=tokens_in, tokens_out=tokens_out)
        text = _persist(user_id=uid, session_id=sid, message=message.strip(), text=text, identity=identity, model_variant=model_variant)
    return {
        "text": text,
        "chunks": chunks,
        "cancelled": cancelled,
        "finish_reason": "cancelled" if cancelled else "stop",
        "model": served,
        "backend": "ollama",
        "identity": identity,
        "live": False if synthetic_provider else probe["status"] == "reachable",
        "synthetic_provider": bool(synthetic_provider),
        "native_family": None,
        "path": "/api/chat",
        "session_id": sid,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "handlers_forcibly_stopped": False,
    }


async def stream_via_gateway(
    *,
    user: object,
    message: str,
    model: str,
    host: str,
    session_id: str,
    model_variant: str = "nano",
    cancel: threading.Event | None = None,
    synthetic_provider: bool = False,
    timeout_s: float = 30.0,
):
    """Yield SSE dicts from OllamaRuntime.stream (/api/chat). Cooperative cancel only."""
    uid = authorize_serving(user=user, message=message, model=model, model_variant=model_variant)
    sid = bind_session(user_id=uid, session_id=session_id)
    lock = _session_lock(sid)
    await asyncio.to_thread(lock.acquire)
    try:
        async for item in _stream_via_gateway_locked(
            uid=uid,
            sid=sid,
            message=message,
            model=model,
            host=host,
            model_variant=model_variant,
            cancel=cancel,
            synthetic_provider=synthetic_provider,
            timeout_s=timeout_s,
        ):
            yield item
    finally:
        lock.release()


async def _stream_via_gateway_locked(
    *,
    uid: str,
    sid: str,
    message: str,
    model: str,
    host: str,
    model_variant: str,
    cancel: threading.Event | None,
    synthetic_provider: bool,
    timeout_s: float,
):
    probe = probe_ollama(host=host, timeout_s=2.0)
    if probe["status"] != "reachable":
        raise InferenceError("provider_unavailable")
    request_id = uuid.uuid4().hex
    runtime = runtime_for(host, timeout_s=timeout_s)
    request = InferenceRequest(
        request_id=request_id,
        model_id=model,
        model_version=model,
        messages=_messages_with_session(sid, message.strip()),
        max_tokens=64,
        temperature=0.0,
        tenant_id=uid,
        session_id=sid,
        timeout_s=timeout_s,
    )
    chunks: list[str] = []
    cancelled = False
    tokens_in = 0
    tokens_out = 0
    try:
        async for chunk in runtime.stream(request):
            if cancel is not None and cancel.is_set():
                await runtime.cancel(request_id)
                cancelled = True
                yield {
                    "type": "cancelled",
                    "finish_reason": "cancelled",
                    "handlers_forcibly_stopped": False,
                    "session_id": sid,
                }
                break
            if chunk.delta:
                safe_delta = _safe_text(chunk.delta)
                chunks.append(safe_delta)
                yield {"type": "chunk", "text": safe_delta, "path": "/api/chat", "backend": "ollama", "session_id": sid}
            if chunk.finish_reason == "cancelled":
                cancelled = True
                yield {
                    "type": "cancelled",
                    "finish_reason": "cancelled",
                    "handlers_forcibly_stopped": False,
                    "session_id": sid,
                }
                break
            if chunk.finish_reason == "stop":
                tokens_in = int(chunk.prompt_tokens or 0)
                tokens_out = int(chunk.completion_tokens or 0)
                break
    except RequestCancelledError:
        cancelled = True
        yield {"type": "cancelled", "finish_reason": "cancelled", "handlers_forcibly_stopped": False, "session_id": sid}
    except GenerationTimeoutError as exc:
        raise InferenceError("provider_timeout") from exc
    except DeploymentUnavailableError as exc:
        raise InferenceError("provider_unavailable") from exc
    text = "".join(chunks)
    if not cancelled:
        record_usage(user_id=uid, model=model, backend="ollama", tokens_in=tokens_in, tokens_out=tokens_out)
        identity = _identity(model)
        text = _persist(user_id=uid, session_id=sid, message=message.strip(), text=text, identity=identity, model_variant=model_variant)
        yield {
            "type": "done",
            "text": text,
            "model": model,
            "backend": "ollama",
            "identity": identity,
            "native_family": None,
            "live": not synthetic_provider,
            "synthetic_provider": bool(synthetic_provider),
            "path": "/api/chat",
            "session_id": sid,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "finish_reason": "stop",
            "handlers_forcibly_stopped": False,
        }


def refuse_paid(*, backend: str) -> None:
    if backend in PAID_BACKENDS and not spending_authorized():
        raise InferenceError("paid_backend_refused")
