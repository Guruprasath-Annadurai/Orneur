"""Authenticated local inference through the Ollama adapter.

Does not impersonate GENESIS, NOVUS, or AETERNUM. Live Ollama is used when
the host answers /api/generate and /api/chat. Unreachable providers stay
unavailable. Fixture HTTP servers used in tests must set synthetic_provider.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from orca.gateway.contracts import InferenceRequest
from orca.gateway.errors import DeploymentUnavailableError, GenerationTimeoutError, RequestCancelledError
from orca.gateway.ollama_runtime import OllamaRuntime
from orca.rse.imp1.locks import spending_authorized
from orca.serve.availability import probe_ollama
from orca.serve.model_identity import model_identity
from orca.serve.usage import NATIVE_FAMILIES, PAID_BACKENDS, record_usage

_LOCK = threading.Lock()
_TEST_DB: Path | None = None
_MAX_TURNS = 20
_NATIVE_PREFIXES = ("genesis", "novus", "aeternum", "orneur-genesis", "orneur-novus", "orneur-aeternum")


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


def set_history_path(path: Path | None) -> None:
    global _TEST_DB
    _TEST_DB = path


def _db_path() -> Path:
    if _TEST_DB is not None:
        return _TEST_DB
    from orca.config import ORCA_HOME

    return ORCA_HOME / "inference_turns.sqlite"


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS turns (user_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, ts REAL NOT NULL)"
    )
    return conn


def history(user_id: str) -> list[dict]:
    with _LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT role, content FROM turns WHERE user_id = ? ORDER BY ts ASC, rowid ASC",
                (user_id,),
            ).fetchall()
        finally:
            conn.close()
    return [{"role": role, "content": content} for role, content in rows]


def reset_for_tests() -> None:
    with _LOCK:
        conn = _connect()
        try:
            conn.execute("DELETE FROM turns")
            conn.commit()
        finally:
            conn.close()


def _append(user_id: str, role: str, content: str) -> None:
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                "INSERT INTO turns (user_id, role, content, ts) VALUES (?, ?, ?, ?)",
                (user_id, role, content, time.time()),
            )
            conn.execute(
                """
                DELETE FROM turns WHERE user_id = ? AND rowid NOT IN (
                    SELECT rowid FROM turns WHERE user_id = ? ORDER BY ts DESC, rowid DESC LIMIT ?
                )
                """,
                (user_id, user_id, _MAX_TURNS * 2),
            )
            conn.commit()
        finally:
            conn.close()


def _prompt_with_history(user_id: str, message: str) -> str:
    parts = [f"{row['role']}: {row['content']}" for row in history(user_id)]
    parts.append(f"user: {message}")
    return "\n".join(parts)


def _messages_with_history(user_id: str, message: str) -> list[dict]:
    rows = history(user_id)
    return [*rows, {"role": "user", "content": message}]


def _identity(served: str) -> dict:
    return model_identity(
        requested_variant=None,
        served_tier=None,
        served_model=served,
        backend="ollama",
        data_left_infrastructure=False,
    )


def complete(
    *,
    user: object,
    message: str,
    model: str,
    host: str,
    transport_generate=None,
    synthetic_provider: bool = False,
    timeout_s: float = 30.0,
) -> dict:
    uid = _user_id(user)
    if not isinstance(message, str) or not message.strip():
        raise InferenceError("prompt_refused")
    if not isinstance(model, str) or not model.strip():
        raise InferenceError("model_refused")
    if _native_refused(model):
        raise InferenceError("native_identity_refused")
    probe = probe_ollama(host=host, timeout_s=2.0)
    if probe["status"] != "reachable" and transport_generate is None:
        raise InferenceError("provider_unavailable")
    prompt = _prompt_with_history(uid, message.strip())
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
    _append(uid, "user", message.strip())
    _append(uid, "assistant", text)
    return {
        "text": text,
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
    transport_stream=None,
    cancel: threading.Event | None = None,
    synthetic_provider: bool = False,
    timeout_s: float = 30.0,
) -> dict:
    uid = _user_id(user)
    if not isinstance(message, str) or not message.strip():
        raise InferenceError("prompt_refused")
    if _native_refused(model):
        raise InferenceError("native_identity_refused")
    probe = probe_ollama(host=host, timeout_s=2.0)
    if probe["status"] != "reachable" and transport_stream is None:
        raise InferenceError("provider_unavailable")
    chunks: list[str] = []
    cancelled = False
    tokens_in = 0
    tokens_out = 0
    served = model
    messages = _messages_with_history(uid, message.strip())
    if transport_stream is not None:
        for delta in transport_stream(host, model, message.strip()):
            if cancel is not None and cancel.is_set():
                cancelled = True
                break
            if delta:
                chunks.append(delta)
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
                        chunks.append(piece)
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
        _append(uid, "user", message.strip())
        _append(uid, "assistant", text)
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
    cancel: threading.Event | None = None,
    synthetic_provider: bool = False,
    timeout_s: float = 30.0,
):
    """Yield SSE dicts from OllamaRuntime.stream (/api/chat). Cooperative cancel only."""
    uid = _user_id(user)
    if not isinstance(message, str) or not message.strip():
        raise InferenceError("prompt_refused")
    if _native_refused(model):
        raise InferenceError("native_identity_refused")
    probe = probe_ollama(host=host, timeout_s=2.0)
    if probe["status"] != "reachable":
        raise InferenceError("provider_unavailable")
    request_id = uuid.uuid4().hex
    runtime = runtime_for(host, timeout_s=timeout_s)
    request = InferenceRequest(
        request_id=request_id,
        model_id=model,
        model_version=model,
        messages=_messages_with_history(uid, message.strip()),
        max_tokens=64,
        temperature=0.0,
        tenant_id=uid,
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
                }
                break
            if chunk.delta:
                chunks.append(chunk.delta)
                yield {"type": "chunk", "text": chunk.delta, "path": "/api/chat", "backend": "ollama"}
            if chunk.finish_reason == "cancelled":
                cancelled = True
                yield {
                    "type": "cancelled",
                    "finish_reason": "cancelled",
                    "handlers_forcibly_stopped": False,
                }
                break
            if chunk.finish_reason == "stop":
                tokens_in = int(chunk.prompt_tokens or 0)
                tokens_out = int(chunk.completion_tokens or 0)
                break
    except RequestCancelledError:
        cancelled = True
        yield {"type": "cancelled", "finish_reason": "cancelled", "handlers_forcibly_stopped": False}
    except GenerationTimeoutError as exc:
        raise InferenceError("provider_timeout") from exc
    except DeploymentUnavailableError as exc:
        raise InferenceError("provider_unavailable") from exc
    text = "".join(chunks)
    if not cancelled:
        record_usage(user_id=uid, model=model, backend="ollama", tokens_in=tokens_in, tokens_out=tokens_out)
        _append(uid, "user", message.strip())
        _append(uid, "assistant", text)
        yield {
            "type": "done",
            "text": text,
            "model": model,
            "backend": "ollama",
            "identity": _identity(model),
            "native_family": None,
            "live": not synthetic_provider,
            "synthetic_provider": bool(synthetic_provider),
            "path": "/api/chat",
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "finish_reason": "stop",
            "handlers_forcibly_stopped": False,
        }


def refuse_paid(*, backend: str) -> None:
    if backend in PAID_BACKENDS and not spending_authorized():
        raise InferenceError("paid_backend_refused")
