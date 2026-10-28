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

from orca.auth.store import (
    QuotaError,
    claim_session,
    mark_quota_consumed,
    release_quota,
    reservation_fingerprint,
    reserve_quota,
)
from orca.gateway.contracts import InferenceRequest
from orca.gateway.errors import DeploymentUnavailableError, GenerationTimeoutError, RequestCancelledError
from orca.gateway.ollama_runtime import OllamaRuntime
from orca.rse.imp1.locks import spending_authorized
from orca.serve import conversations, session_store
from orca.serve.availability import probe_ollama
from orca.serve.model_catalog import CatalogError, authorize_model
from orca.serve.model_identity import model_identity
from orca.serve.moderation import check_input
from orca.serve.stream_dlp import StreamRedactor, redact_structure
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


def authorize_serving(*, user: object, message: str, model: str, model_variant: str | None = None) -> str:
    uid = _user_id(user)
    if not isinstance(message, str) or not message.strip():
        raise InferenceError("prompt_refused")
    if not isinstance(model, str) or not model.strip():
        raise InferenceError("model_refused")
    lowered = model.strip().lower()
    if any(lowered.startswith(p) for p in ("gpt-", "claude", "gemini", "openai", "anthropic")):
        refuse_paid(backend="openai")
    if not spending_authorized() and lowered in PAID_BACKENDS:
        refuse_paid(backend=lowered)
    try:
        authorize_model(user=user, model=model, claimed_variant=model_variant)
    except CatalogError as exc:
        raise InferenceError(exc.code) from exc
    if check_input(message).action == "block":
        raise InferenceError("content_refused")
    return uid


def _admit_quota(
    *,
    user: object,
    request_id: str,
    fingerprint: str | None = None,
) -> dict:
    """Admit one billable unit. Returns the reservation dict.

    ``ok`` is True only for a fresh reservation that may dispatch a provider
    call. Consumed matches may carry ``replay`` for idempotent response
    return without redispatch.
    """
    try:
        reservation = reserve_quota(
            _user_id(user),
            getattr(user, "tier", "free") or "free",
            "message",
            request_id=request_id,
            fingerprint=fingerprint,
        )
    except QuotaError as exc:
        raise InferenceError(exc.code) from exc
    if reservation.get("ok"):
        return reservation
    status = reservation.get("status")
    if status == "consumed" and reservation.get("replay") is not None:
        return reservation
    if status in {"released", "consumed"}:
        raise InferenceError("quota_exceeded")
    if status == "in_progress":
        raise InferenceError("request_in_progress")
    raise InferenceError("quota_exceeded")


def _consume_quota(request_id: str, response: dict | None = None) -> None:
    try:
        mark_quota_consumed(request_id, response=response)
    except QuotaError as exc:
        raise InferenceError(exc.code) from exc


def _acquire_turn(session_id: str) -> str:
    fence = uuid.uuid4().hex
    if not session_store.acquire_session_lease(session_id, fence, ttl_ms=45_000):
        raise InferenceError("session_busy")
    return fence


def _session_lock(session_id: str) -> threading.Lock:
    with _TURN_LOCKS_GUARD:
        lock = _TURN_LOCKS.get(session_id)
        if lock is None:
            lock = threading.Lock()
            _TURN_LOCKS[session_id] = lock
        return lock


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


def _persist(
    *,
    user_id: str,
    session_id: str,
    message: str,
    text: str,
    identity: dict,
    model: str,
    model_variant: str | None = None,
    fence_token: str | None = None,
) -> str:
    """Authoritative turn commit: fence claim → atomic turn → Redis stamp.

    JSONL alone cannot enforce lease/revision atomicity. The protocol is:
    1. Load expected conversation revision.
    2. ``claim_turn_commit`` verifies the worker fence and bumps revision
       (stale workers whose lease expired receive None and write nothing).
    3. ``conversations.commit_turn`` writes the SQLite authoritative turn
       and a single JSONL export of both messages (no split pair).
    4. Redis session payload is stamped with the claimed revision under the
       same fence. Failure here does not roll back the durable turn; readers
       rebuild from the transcript.
    """
    from orca.serve.dlp import scan_output
    from orca.serve.model_catalog import lookup

    safe = scan_output(text or "")["safe_text"]
    _state, rev = session_store.load_session_state_with_revision(session_id)
    new_rev = session_store.claim_turn_commit(session_id, fence_token or "", rev)
    if new_rev is None:
        raise InferenceError("stale_worker")
    turn_id = uuid.uuid4().hex
    committed = conversations.commit_turn(
        session_id,
        message,
        safe,
        user_id=user_id,
        turn_id=turn_id,
        revision=int(new_rev),
        meta={"model_identity": identity},
    )
    if not committed.ok:
        raise InferenceError("persist_failed")
    entry = lookup(model)
    stored_tier = (entry.tier if entry else None) or model_variant or "nano"
    session_store.save_session_state(
        session_id,
        stored_tier,
        _session_messages(session_id),
        expected_revision=int(new_rev),
        fence_token=fence_token,
    )
    session_store.touch_session(session_id)
    return safe


def complete(
    *,
    user: object,
    message: str,
    model: str,
    host: str,
    session_id: str,
    model_variant: str | None = None,
    transport_generate=None,
    synthetic_provider: bool = False,
    timeout_s: float = 30.0,
    request_id: str | None = None,
) -> dict:
    uid = authorize_serving(user=user, message=message, model=model, model_variant=model_variant)
    sid = bind_session(user_id=uid, session_id=session_id)
    with _session_lock(sid):
        fence = _acquire_turn(sid)
        try:
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
                request_id=request_id,
                fence_token=fence,
                user=user,
            )
        finally:
            session_store.release_session_lease(sid, fence)


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
    request_id: str | None,
    fence_token: str,
    user: object,
) -> dict:
    probe = probe_ollama(host=host, timeout_s=2.0)
    if probe["status"] != "reachable" and transport_generate is None:
        raise InferenceError("provider_unavailable")
    msg = message.strip()
    fp = reservation_fingerprint(user_id=uid, kind="message", session_id=sid, model=model, message=msg)
    admission = _admit_quota(user=user, request_id=request_id or uuid.uuid4().hex, fingerprint=fp)
    if admission.get("status") == "consumed" and admission.get("replay") is not None:
        replay = dict(admission["replay"])
        replay["request_id"] = admission["request_id"]
        replay["replayed"] = True
        return replay
    rid = admission["request_id"]
    consumed = False
    prompt = _prompt_with_session(sid, msg)
    t0 = time.monotonic()
    try:
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
        safe = _persist(
            user_id=uid,
            session_id=sid,
            message=msg,
            text=text,
            identity=identity,
            model=model,
            model_variant=model_variant,
            fence_token=fence_token,
        )
        result = {
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
            "request_id": rid,
        }
        _consume_quota(rid, response=result)
        consumed = True
        return result
    finally:
        if not consumed:
            try:
                release_quota(rid)
            except QuotaError:
                pass


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
        fence = _acquire_turn(sid)
        try:
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
                user=user,
                fence_token=fence,
            )
        finally:
            session_store.release_session_lease(sid, fence)


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
    user: object,
    fence_token: str,
) -> dict:
    probe = probe_ollama(host=host, timeout_s=2.0)
    if probe["status"] != "reachable" and transport_stream is None:
        raise InferenceError("provider_unavailable")
    msg = message.strip()
    fp = reservation_fingerprint(user_id=uid, kind="message", session_id=sid, model=model, message=msg)
    admission = _admit_quota(user=user, request_id=uuid.uuid4().hex, fingerprint=fp)
    if admission.get("status") == "consumed" and admission.get("replay") is not None:
        replay = dict(admission["replay"])
        replay["request_id"] = admission["request_id"]
        replay["replayed"] = True
        return replay
    rid = admission["request_id"]
    consumed = False
    redactor = StreamRedactor()
    chunks: list[str] = []
    cancelled = False
    finished = False
    tokens_in = 0
    tokens_out = 0
    served = model
    messages = _messages_with_session(sid, msg)
    try:
        if transport_stream is not None:
            for delta in transport_stream(host, model, msg):
                if cancel is not None and cancel.is_set():
                    cancelled = True
                    break
                if delta:
                    piece = redactor.push(delta)
                    if piece:
                        chunks.append(piece)
            if not cancelled:
                finished = True
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
                            safe_piece = redactor.push(piece)
                            if safe_piece:
                                chunks.append(safe_piece)
                        if payload.get("done"):
                            tokens_in = int(payload.get("prompt_eval_count") or 0)
                            tokens_out = int(payload.get("eval_count") or 0)
                            finished = True
                            break
            except httpx.TimeoutException as exc:
                raise InferenceError("provider_timeout") from exc
            except Exception as exc:
                raise InferenceError("provider_unavailable") from exc
        if cancelled:
            redactor.cancel()
            if chunks:
                _consume_quota(rid)
                consumed = True
            return {
                "text": "",
                "chunks": chunks,
                "cancelled": True,
                "finish_reason": "cancelled",
                "model": served,
                "backend": "ollama",
                "identity": _identity(served),
                "live": False if synthetic_provider else probe["status"] == "reachable",
                "synthetic_provider": bool(synthetic_provider),
                "native_family": None,
                "path": "/api/chat",
                "session_id": sid,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "handlers_forcibly_stopped": False,
            }
        if not finished:
            raise InferenceError("provider_unavailable")
        if _native_refused(served):
            raise InferenceError("native_identity_refused")
        tail = redactor.finish()
        if tail:
            chunks.append(tail)
        text = "".join(chunks)
        identity = _identity(served)
        record_usage(user_id=uid, model=served, backend="ollama", tokens_in=tokens_in, tokens_out=tokens_out)
        text = _persist(
            user_id=uid,
            session_id=sid,
            message=msg,
            text=text,
            identity=identity,
            model=model,
            model_variant=model_variant,
            fence_token=fence_token,
        )
        # Persist already applied DLP; keep emitted chunks consistent with stored text.
        if text != "".join(chunks):
            chunks = [text]
        result = {
            "text": text,
            "chunks": chunks,
            "cancelled": False,
            "finish_reason": "stop",
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
            "request_id": rid,
        }
        _consume_quota(rid, response=result)
        consumed = True
        return result
    finally:
        if not consumed:
            try:
                release_quota(rid)
            except QuotaError:
                pass


async def stream_via_gateway(
    *,
    user: object,
    message: str,
    model: str,
    host: str,
    session_id: str,
    model_variant: str | None = None,
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
        fence = _acquire_turn(sid)
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
                user=user,
                fence_token=fence,
            ):
                yield redact_structure(item)
        finally:
            session_store.release_session_lease(sid, fence)
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
    user: object,
    fence_token: str,
):
    probe = probe_ollama(host=host, timeout_s=2.0)
    if probe["status"] != "reachable":
        raise InferenceError("provider_unavailable")
    msg = message.strip()
    fp = reservation_fingerprint(user_id=uid, kind="message", session_id=sid, model=model, message=msg)
    admission = _admit_quota(user=user, request_id=uuid.uuid4().hex, fingerprint=fp)
    if admission.get("status") == "consumed" and admission.get("replay") is not None:
        replay = dict(admission["replay"])
        replay["type"] = "done"
        replay["replayed"] = True
        yield replay
        return
    rid = admission["request_id"]
    consumed = False
    redactor = StreamRedactor()
    request_id = uuid.uuid4().hex
    runtime = runtime_for(host, timeout_s=timeout_s)
    request = InferenceRequest(
        request_id=request_id,
        model_id=model,
        model_version=model,
        messages=_messages_with_session(sid, msg),
        max_tokens=64,
        temperature=0.0,
        tenant_id=uid,
        session_id=sid,
        timeout_s=timeout_s,
    )
    chunks: list[str] = []
    cancelled = False
    finished = False
    tokens_in = 0
    tokens_out = 0
    try:
        try:
            async for chunk in runtime.stream(request):
                if cancel is not None and cancel.is_set():
                    await runtime.cancel(request_id)
                    cancelled = True
                    redactor.cancel()
                    yield {
                        "type": "cancelled",
                        "finish_reason": "cancelled",
                        "handlers_forcibly_stopped": False,
                        "session_id": sid,
                    }
                    break
                if chunk.delta:
                    safe_delta = redactor.push(chunk.delta)
                    if safe_delta:
                        chunks.append(safe_delta)
                        yield {"type": "chunk", "text": safe_delta, "path": "/api/chat", "backend": "ollama", "session_id": sid}
                if chunk.finish_reason == "cancelled":
                    cancelled = True
                    redactor.cancel()
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
                    finished = True
                    break
        except RequestCancelledError:
            cancelled = True
            redactor.cancel()
            yield {"type": "cancelled", "finish_reason": "cancelled", "handlers_forcibly_stopped": False, "session_id": sid}
        except GenerationTimeoutError as exc:
            raise InferenceError("provider_timeout") from exc
        except DeploymentUnavailableError as exc:
            raise InferenceError("provider_unavailable") from exc
        if cancelled:
            if chunks:
                _consume_quota(rid)
                consumed = True
            return
        if not finished:
            raise InferenceError("provider_unavailable")
        tail = redactor.finish()
        if tail:
            chunks.append(tail)
            yield {"type": "chunk", "text": tail, "path": "/api/chat", "backend": "ollama", "session_id": sid}
        text = "".join(chunks)
        record_usage(user_id=uid, model=model, backend="ollama", tokens_in=tokens_in, tokens_out=tokens_out)
        identity = _identity(model)
        text = _persist(
            user_id=uid,
            session_id=sid,
            message=msg,
            text=text,
            identity=identity,
            model=model,
            model_variant=model_variant,
            fence_token=fence_token,
        )
        done = {
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
            "request_id": rid,
        }
        _consume_quota(rid, response=done)
        consumed = True
        yield done
    finally:
        if not consumed:
            try:
                release_quota(rid)
            except QuotaError:
                pass


def refuse_paid(*, backend: str) -> None:
    if backend in PAID_BACKENDS and not spending_authorized():
        raise InferenceError("paid_backend_refused")
