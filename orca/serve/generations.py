"""Server-side generation identity for one conversation turn.

A generation id is not a model claim and not a tool grant. It names one
execution attempt so a client can read the terminal state after the
socket closes, and can ask this process to stop a cancellable stream.

Retry eligibility means the client may send a new `/api/stream` request.
It does not resume, replay, or regenerate the previous attempt.

Records live under the isolated memory directory. A running record whose
heartbeat is older than `STALE_AFTER` seconds is reported as
`interrupted_unknown`. That is an observation, not a new grant.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path

STALE_AFTER = 30.0
_ID = re.compile(r"^[0-9a-f]{32}$")
_KEY = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
_TERMINAL = {"completed", "cancelled", "failed"}
_RETRYABLE = {"cancelled", "failed", "interrupted_unknown"}


class GenerationDenied(PermissionError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _dir() -> Path:
    import orca.brain.memory as mem

    directory = Path(mem.MEMORY_DIR) / "generations"
    directory.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    return directory


def _path(generation_id: str) -> Path:
    if not isinstance(generation_id, str) or _ID.fullmatch(generation_id) is None:
        raise GenerationDenied("generation id is not valid")
    return _dir() / f"{generation_id}.json"


def _write(path: Path, payload: dict) -> None:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0), 0o600)
    try:
        os.write(fd, raw)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def _read_path(path: Path) -> dict | None:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    try:
        payload = json.loads(raw.decode())
    except (UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def read(generation_id: str) -> dict | None:
    try:
        path = _path(generation_id)
    except GenerationDenied:
        return None
    return _read_path(path)


def public(record: dict, *, now: float | None = None, stale_after: float = STALE_AFTER) -> dict:
    moment = time.time() if now is None else now
    state = record.get("state")
    if state == "running" and moment - float(record.get("updated_at") or 0) > stale_after:
        state = "interrupted_unknown"
    return {
        "generation_id": record.get("generation_id"),
        "session_id": record.get("session_id"),
        "state": state,
        "cancel_requested": bool(record.get("cancel_requested")),
        "delivery": record.get("delivery"),
        "cancellable": bool(record.get("cancellable")),
        "retry_eligible": state in _RETRYABLE,
        "terminal": state != "running",
        "reason": record.get("reason"),
    }


def allowed(record: dict, user_id: str | None) -> bool:
    from orca.auth.store import check_session_access

    if not check_session_access(str(record.get("session_id") or ""), user_id):
        return False
    return record.get("user_id") == user_id


def _owner_component(user_id: str | None) -> str:
    if user_id is None:
        return "anonymous"
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", user_id):
        raise GenerationDenied("owner id is not a single path component")
    return user_id


def _idem_path(user_id: str | None, session_id: str, key: str) -> Path:
    digest = hashlib.sha256(key.encode()).hexdigest()
    directory = _dir() / "idempotency" / _owner_component(user_id)
    directory.mkdir(parents=True, exist_ok=True)
    safe_session = session_id if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", session_id) else None
    if safe_session is None:
        raise GenerationDenied("session id is not valid")
    return directory / f"{safe_session}-{digest}.json"


def begin(
    *,
    session_id: str,
    user_id: str | None,
    delivery: str,
    cancellable: bool,
    idempotency_key: str | None = None,
) -> tuple[dict, bool]:
    if idempotency_key is not None and _KEY.fullmatch(idempotency_key) is None:
        raise GenerationDenied("idempotency key is not valid")
    if idempotency_key:
        existing = _read_path(_idem_path(user_id, session_id, idempotency_key))
        if existing and isinstance(existing.get("generation_id"), str):
            found = read(existing["generation_id"])
            if found is not None:
                return found, False
    now = time.time()
    record = {
        "version": 1,
        "generation_id": uuid.uuid4().hex,
        "session_id": session_id,
        "user_id": user_id,
        "state": "running",
        "delivery": delivery,
        "cancellable": bool(cancellable),
        "cancel_requested": False,
        "idempotency_key": idempotency_key,
        "created_at": now,
        "updated_at": now,
        "reason": None,
    }
    _write(_path(record["generation_id"]), record)
    if not idempotency_key:
        return record, True
    path = _idem_path(user_id, session_id, idempotency_key)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        os.unlink(_path(record["generation_id"]))
        winner = _read_path(path)
        found = read(winner["generation_id"]) if winner else None
        if found is None:
            raise GenerationDenied("idempotency key is already used")
        return found, False
    try:
        os.write(fd, json.dumps({"generation_id": record["generation_id"]}).encode())
    finally:
        os.close(fd)
    return record, True


def touch(generation_id: str) -> None:
    record = read(generation_id)
    if record is None or record.get("state") != "running":
        return
    record["updated_at"] = time.time()
    _write(_path(generation_id), record)


def cancel_requested(generation_id: str) -> bool:
    record = read(generation_id)
    return bool(record and record.get("cancel_requested") and record.get("state") == "running")


def finish(generation_id: str, state: str, *, reason: str | None = None) -> dict | None:
    if state not in _TERMINAL:
        raise GenerationDenied("terminal state is not valid")
    record = read(generation_id)
    if record is None:
        return None
    if record.get("state") != "running":
        return record
    record["state"] = state
    record["reason"] = reason
    record["updated_at"] = time.time()
    _write(_path(generation_id), record)
    return record


def request_cancel(generation_id: str) -> dict:
    record = read(generation_id)
    if record is None:
        raise GenerationDenied("generation was not found")
    view = public(record)
    if not record.get("cancellable"):
        view["cancel_accepted"] = False
        view["code"] = "generation_not_cancellable"
        return view
    if record.get("state") != "running":
        view["cancel_accepted"] = False
        view["code"] = "generation_already_terminal"
        return view
    if view["state"] == "interrupted_unknown":
        finish(generation_id, "cancelled", reason="stale_worker")
        view = public(read(generation_id) or record)
        view["cancel_accepted"] = True
        view["code"] = "cancel_requested"
        return view
    record["cancel_requested"] = True
    record["updated_at"] = time.time()
    _write(_path(generation_id), record)
    view = public(record)
    view["cancel_accepted"] = True
    view["code"] = "cancel_requested"
    return view


def existing_http(record: dict) -> tuple[int, dict]:
    """Status for a repeated idempotency key. Does not run the model again."""
    view = public(record)
    if view["state"] == "running":
        view["code"] = "generation_in_progress"
        return 409, view
    if view["state"] == "completed":
        view["code"] = "generation_already_completed"
        return 200, view
    view["code"] = "generation_not_reusable"
    return 409, view
