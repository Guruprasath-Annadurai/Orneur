"""Server-side generation identity for one conversation turn.

A generation id is not a model claim and not a tool grant. It names one
execution attempt so a client can read the terminal state after the
socket closes, and can ask this process to stop a cancellable stream.

State changes are one read-modify-write under an exclusive file lock.
`cancelled` and `completed` are written only by `finish`, after the
worker has stopped or the output is actually done. A cancel request
sets a flag. It does not itself claim the run has stopped.

The owning request holds a live lock and refreshes the heartbeat while
a chunk is in flight. A gap longer than `STALE_AFTER` is reported as
`interrupted_unknown` only when that heartbeat has stopped. The stored
state stays `running` until a real transition.

Retry eligibility means the client may send a new `/api/stream` request.
It does not resume, replay, or regenerate the previous attempt.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

STALE_AFTER = 30.0
_HEARTBEAT_INTERVAL = 5.0
_ID = re.compile(r"^[0-9a-f]{32}$")
_KEY = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
_TERMINAL = {"completed", "cancelled", "failed"}
_RETRYABLE = {"cancelled", "failed", "interrupted_unknown"}

# Test seam. Production leaves this None. "after-idempotency-reserve"
# raises after the key file is durable and before the generation record.
publish_fault: str | None = None


class GenerationDenied(PermissionError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class GenerationMismatch(GenerationDenied):
    """The idempotency key was already used for a different request body."""

    def __init__(self, reason: str, generation_id: str | None = None):
        super().__init__(reason)
        self.generation_id = generation_id


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


def _fsync_dir(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


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
    try:
        _fsync_dir(path.parent)
    except OSError:
        pass


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


@contextmanager
def _flock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield fd
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _record_lock(generation_id: str):
    return _flock(_path(generation_id).with_suffix(".lock"))


def read(generation_id: str) -> dict | None:
    try:
        path = _path(generation_id)
    except GenerationDenied:
        return None
    with _record_lock(generation_id):
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


def fingerprint(*, message: str, session_id: str, model_variant: str | None) -> str:
    payload = {"message": message, "session_id": session_id, "model_variant": model_variant or ""}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


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


def _blank_record(
    *,
    generation_id: str,
    session_id: str,
    user_id: str | None,
    delivery: str,
    cancellable: bool,
    idempotency_key: str | None,
    request_hash: str | None,
) -> dict:
    now = time.time()
    return {
        "version": 1,
        "generation_id": generation_id,
        "session_id": session_id,
        "user_id": user_id,
        "state": "running",
        "delivery": delivery,
        "cancellable": bool(cancellable),
        "cancel_requested": False,
        "idempotency_key": idempotency_key,
        "request_hash": request_hash,
        "created_at": now,
        "updated_at": now,
        "reason": None,
    }


def begin(
    *,
    session_id: str,
    user_id: str | None,
    delivery: str,
    cancellable: bool,
    idempotency_key: str | None = None,
    request_hash: str | None = None,
) -> tuple[dict, bool]:
    if idempotency_key is not None and _KEY.fullmatch(idempotency_key) is None:
        raise GenerationDenied("idempotency key is not valid")
    if idempotency_key is None:
        record = _blank_record(
            generation_id=uuid.uuid4().hex,
            session_id=session_id,
            user_id=user_id,
            delivery=delivery,
            cancellable=cancellable,
            idempotency_key=None,
            request_hash=None,
        )
        with _record_lock(record["generation_id"]):
            _write(_path(record["generation_id"]), record)
        return record, True
    if not isinstance(request_hash, str) or len(request_hash) != 64:
        raise GenerationDenied("idempotency request hash is required")
    path = _idem_path(user_id, session_id, idempotency_key)
    with _flock(path.with_suffix(".lock")):
        existing = _read_path(path)
        if existing and isinstance(existing.get("generation_id"), str):
            if existing.get("request_hash") != request_hash:
                raise GenerationMismatch(
                    "idempotency key was used for a different request",
                    generation_id=existing.get("generation_id"),
                )
            record_path = _path(existing["generation_id"])
            if record_path.exists():
                found = read(existing["generation_id"])
                if found is None:
                    raise GenerationDenied("generation record is unreadable")
                return found, False
            record = _blank_record(
                generation_id=existing["generation_id"],
                session_id=session_id,
                user_id=user_id,
                delivery=delivery,
                cancellable=cancellable,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
            with _record_lock(record["generation_id"]):
                already = _read_path(_path(record["generation_id"]))
                if already is not None:
                    return already, False
                _write(_path(record["generation_id"]), record)
            return record, True
        generation_id = uuid.uuid4().hex
        _write(path, {"generation_id": generation_id, "request_hash": request_hash})
        if publish_fault == "after-idempotency-reserve":
            raise RuntimeError("publication interrupted")
        record = _blank_record(
            generation_id=generation_id,
            session_id=session_id,
            user_id=user_id,
            delivery=delivery,
            cancellable=cancellable,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        with _record_lock(generation_id):
            _write(_path(generation_id), record)
        return record, True


def _mutate(generation_id: str, apply) -> dict | None:
    with _record_lock(generation_id):
        record = _read_path(_path(generation_id))
        if record is None:
            return None
        updated = apply(dict(record))
        if updated is None:
            return record
        _write(_path(generation_id), updated)
        return updated


def touch(generation_id: str) -> None:
    def apply(record: dict):
        if record.get("state") != "running":
            return None
        record["updated_at"] = time.time()
        return record

    _mutate(generation_id, apply)


def cancel_requested(generation_id: str) -> bool:
    record = read(generation_id)
    return bool(record and record.get("cancel_requested") and record.get("state") == "running")


def finish(generation_id: str, state: str, *, reason: str | None = None) -> dict | None:
    if state not in _TERMINAL:
        raise GenerationDenied("terminal state is not valid")

    def apply(record: dict):
        if record.get("state") != "running":
            return None
        record["state"] = state
        record["reason"] = reason
        record["updated_at"] = time.time()
        return record

    return _mutate(generation_id, apply)


def request_cancel(generation_id: str) -> dict:
    found = {"record": None}

    def apply(record: dict):
        found["record"] = record
        if not record.get("cancellable") or record.get("state") != "running" or record.get("cancel_requested"):
            return None
        record["cancel_requested"] = True
        record["updated_at"] = time.time()
        return record

    updated = _mutate(generation_id, apply)
    record = updated if updated is not None else found["record"]
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


class _Heartbeat:
    def __init__(self, fd: int, thread: threading.Thread, stop: threading.Event):
        self._fd = fd
        self._thread = thread
        self._stop = stop
        self._stopped = False

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._stop.set()
        self._thread.join(timeout=2)
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)


def start_heartbeat(generation_id: str, *, interval: float = _HEARTBEAT_INTERVAL) -> _Heartbeat:
    """Hold the live lock and refresh the heartbeat until `stop`.

    A chunk that takes longer than `STALE_AFTER` does not look abandoned
    while this lock is held and the thread is refreshing the record.
    """
    _path(generation_id)
    live_path = _dir() / f"{generation_id}.live"
    fd = os.open(live_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0), 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    stop = threading.Event()

    def beat() -> None:
        while not stop.wait(interval):
            touch(generation_id)

    thread = threading.Thread(target=beat, name=f"generation-{generation_id[:8]}", daemon=True)
    thread.start()
    return _Heartbeat(fd, thread, stop)


def delete_for_session(session_id: str, user_id: str | None) -> int:
    """Remove generation records and idempotency keys for one session.

    A record whose stored user id is a different account is left in place.
    """
    if not isinstance(session_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", session_id):
        return 0
    removed = 0
    directory = _dir()
    for path in list(directory.glob("*.json")):
        record = _read_path(path)
        if not isinstance(record, dict) or record.get("session_id") != session_id:
            continue
        if user_id is not None and record.get("user_id") not in (user_id, None):
            continue
        generation_id = record.get("generation_id")
        if not isinstance(generation_id, str) or _ID.fullmatch(generation_id) is None:
            continue
        with _record_lock(generation_id):
            current = _read_path(_path(generation_id))
            if not isinstance(current, dict) or current.get("session_id") != session_id:
                continue
            try:
                _path(generation_id).unlink()
                removed += 1
            except FileNotFoundError:
                pass
        for suffix in (".lock", ".live"):
            try:
                _path(generation_id).with_suffix(suffix).unlink()
            except OSError:
                pass
    if user_id is not None:
        try:
            folder = _dir() / "idempotency" / _owner_component(user_id)
        except GenerationDenied:
            return removed
        if folder.exists():
            for path in folder.glob(f"{session_id}-*"):
                try:
                    path.unlink()
                except OSError:
                    continue
    return removed


def worker_alive(generation_id: str) -> bool:
    try:
        _path(generation_id)
    except GenerationDenied:
        return False
    live_path = _dir() / f"{generation_id}.live"
    if not live_path.exists():
        return False
    fd = os.open(live_path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)
