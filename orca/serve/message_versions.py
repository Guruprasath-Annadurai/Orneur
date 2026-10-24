"""Immutable versions of one persisted message.

The conversation JSONL line is never rewritten. An edit or a regeneration
appends a version and moves the active pointer. The original version
stays in the list. A failed regeneration leaves that pointer where it
was.

Ownership of the conversation is checked by the caller. This module
also refuses a version file whose stored user id does not match the
caller, so a planted file is not adopted.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

MAX_VERSIONS = 100
_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_MESSAGE_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_KEY = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
_ROLES = {"user", "assistant"}


class MessageVersionDenied(PermissionError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class MessageVersionMismatch(MessageVersionDenied):
    def __init__(self, reason: str, version_id: str | None = None):
        super().__init__(reason)
        self.version_id = version_id


class MessageVersionInProgress(MessageVersionDenied):
    def __init__(self, reason: str, version_id: str | None = None, generation_id: str | None = None):
        super().__init__(reason)
        self.version_id = version_id
        self.generation_id = generation_id


def fingerprint(op: str, message_id: str, content: str = "") -> str:
    payload = {"op": op, "message_id": message_id, "content": content}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _dir(session_id: str) -> Path:
    import orca.brain.memory as mem

    if _SESSION_ID.fullmatch(session_id or "") is None:
        raise MessageVersionDenied("session id is not valid")
    directory = Path(mem.MEMORY_DIR) / "message_versions" / session_id
    directory.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
        os.chmod(directory.parent, 0o700)
    except OSError:
        pass
    return directory


def _path(session_id: str, message_id: str) -> Path:
    if _MESSAGE_ID.fullmatch(message_id or "") is None:
        raise MessageVersionDenied("message id is not valid")
    return _dir(session_id) / f"{message_id}.json"


def _write(path: Path, payload: dict) -> None:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0), 0o600)
    try:
        os.write(fd, raw)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def _read(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


@contextmanager
def _lock(session_id: str, message_id: str):
    path = _path(session_id, message_id)
    fd = os.open(path.with_suffix(".lock"), os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield path
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _check_owner(record: dict, session_id: str, user_id: str) -> None:
    if record.get("session_id") != session_id or record.get("user_id") != user_id:
        raise MessageVersionDenied("message version was not found")


def _public_version(version: dict) -> dict:
    return {
        "version_id": version.get("version_id"),
        "parent_version_id": version.get("parent_version_id"),
        "content": version.get("content"),
        "created_at": version.get("created_at"),
        "kind": version.get("kind"),
        "generation_id": version.get("generation_id"),
        "committed": bool(version.get("committed")),
    }


def _public(record: dict) -> dict:
    versions = [_public_version(version) for version in record.get("versions") or []]
    active = next((version for version in versions if version["version_id"] == record.get("active_version_id")), None)
    return {
        "message_id": record.get("message_id"),
        "session_id": record.get("session_id"),
        "role": record.get("role"),
        "active_version_id": record.get("active_version_id"),
        "active_content": None if active is None else active["content"],
        "version_count": sum(1 for version in versions if version["committed"]),
        "versions": versions,
    }


def active_view(session_id: str, message_id: str) -> dict | None:
    """Active text for transcript display. Missing files return None."""
    try:
        path = _path(session_id, message_id)
    except MessageVersionDenied:
        return None
    record = _read(path)
    if record is None or record.get("session_id") != session_id:
        return None
    view = _public(record)
    if view["active_content"] is None:
        return None
    return {
        "content": view["active_content"],
        "version_id": view["active_version_id"],
        "version_count": view["version_count"],
        "edited": view["version_count"] > 1,
    }


def read(session_id: str, message_id: str, user_id: str) -> dict:
    with _lock(session_id, message_id):
        record = _read(_path(session_id, message_id))
    if record is None:
        raise MessageVersionDenied("message version was not found")
    _check_owner(record, session_id, user_id)
    return _public(record)


def seed(session_id: str, user_id: str, message_id: str, role: str, content: str) -> dict:
    if role not in _ROLES:
        raise MessageVersionDenied("message role cannot be versioned")
    if not isinstance(user_id, str) or not user_id:
        raise MessageVersionDenied("message version was not found")
    from orca.serve.conversations import MAX_MESSAGE_CHARS

    content = (content or "")[:MAX_MESSAGE_CHARS]
    with _lock(session_id, message_id):
        path = _path(session_id, message_id)
        record = _read(path)
        if record is not None:
            _check_owner(record, session_id, user_id)
            return _public(record)
        version_id = uuid.uuid4().hex
        now = time.time()
        record = {
            "version": 1,
            "message_id": message_id,
            "session_id": session_id,
            "user_id": user_id,
            "role": role,
            "active_version_id": version_id,
            "versions": [{
                "version_id": version_id,
                "parent_version_id": None,
                "content": content,
                "created_at": now,
                "kind": "original",
                "generation_id": None,
                "idempotency_key": None,
                "request_hash": None,
                "committed": True,
            }],
        }
        _write(path, record)
        return _public(record)


def _require_key(key: str | None) -> str | None:
    if key is None:
        return None
    if _KEY.fullmatch(key) is None:
        raise MessageVersionDenied("idempotency key is not valid")
    return key


def _find_key(record: dict, key: str | None) -> dict | None:
    if key is None:
        return None
    for version in record.get("versions") or []:
        if version.get("idempotency_key") == key:
            return version
    return None


def edit(
    session_id: str,
    user_id: str,
    message_id: str,
    content: str,
    *,
    idempotency_key: str | None = None,
) -> dict:
    from orca.serve.conversations import MAX_MESSAGE_CHARS

    key = _require_key(idempotency_key)
    if not isinstance(content, str) or not content.strip():
        raise MessageVersionDenied("message content is empty")
    if len(content) > MAX_MESSAGE_CHARS:
        raise MessageVersionDenied("message content is too long")
    request_hash = fingerprint("edit", message_id, content)
    with _lock(session_id, message_id):
        path = _path(session_id, message_id)
        record = _read(path)
        if record is None:
            raise MessageVersionDenied("message version was not found")
        _check_owner(record, session_id, user_id)
        existing = _find_key(record, key)
        if existing is not None:
            if existing.get("request_hash") != request_hash or existing.get("kind") != "edit":
                raise MessageVersionMismatch("idempotency key was used for a different edit", existing.get("version_id"))
            view = _public(record)
            view["created"] = False
            view["version_id"] = existing.get("version_id")
            return view
        committed = [version for version in record["versions"] if version.get("committed")]
        if len(committed) >= MAX_VERSIONS:
            raise MessageVersionDenied("version history is full")
        version_id = uuid.uuid4().hex
        record["versions"].append({
            "version_id": version_id,
            "parent_version_id": record.get("active_version_id"),
            "content": content,
            "created_at": time.time(),
            "kind": "edit",
            "generation_id": None,
            "idempotency_key": key,
            "request_hash": request_hash,
            "committed": True,
        })
        record["active_version_id"] = version_id
        _write(path, record)
        view = _public(record)
        view["created"] = True
        view["version_id"] = version_id
        return view


def _drop_uncommitted(record: dict, version: dict) -> None:
    from orca.serve import generations

    generation_id = version.get("generation_id")
    if isinstance(generation_id, str) and not generations.worker_alive(generation_id):
        try:
            generations.finish(generation_id, "failed", reason="regeneration_interrupted")
        except generations.GenerationDenied:
            pass
    record["versions"] = [item for item in record["versions"] if item.get("version_id") != version.get("version_id")]


def begin_regeneration(
    session_id: str,
    user_id: str,
    message_id: str,
    *,
    idempotency_key: str | None = None,
) -> dict:
    """Reserve an uncommitted assistant version, or replay a committed one.

    The live generation lock is held before this returns a new attempt.
    A second caller sees that lock and gets `in_progress` instead of a
    second model call. A dead reservation is removed and the generation
    it pointed at is stored as `failed` only when no worker holds the lock.
    """
    from orca.serve import generations

    key = _require_key(idempotency_key)
    request_hash = fingerprint("regenerate", message_id, "")
    heartbeat = None
    with _lock(session_id, message_id):
        path = _path(session_id, message_id)
        record = _read(path)
        if record is None:
            raise MessageVersionDenied("message version was not found")
        _check_owner(record, session_id, user_id)
        if record.get("role") != "assistant":
            raise MessageVersionDenied("only an assistant message can be regenerated")
        existing = _find_key(record, key)
        if existing is not None:
            if existing.get("request_hash") != request_hash or existing.get("kind") != "regeneration":
                raise MessageVersionMismatch(
                    "idempotency key was used for a different regeneration",
                    existing.get("version_id"),
                )
            if existing.get("committed"):
                view = _public(record)
                view["created"] = False
                view["version_id"] = existing.get("version_id")
                view["generation_id"] = existing.get("generation_id")
                return view
            if existing.get("generation_id") and generations.worker_alive(existing["generation_id"]):
                raise MessageVersionInProgress(
                    "regeneration is already in progress",
                    existing.get("version_id"),
                    existing.get("generation_id"),
                )
            _drop_uncommitted(record, existing)
        committed = [version for version in record["versions"] if version.get("committed")]
        if len(committed) >= MAX_VERSIONS:
            raise MessageVersionDenied("version history is full")
        generation, _created = generations.begin(
            session_id=session_id,
            user_id=user_id,
            delivery="regeneration",
            cancellable=False,
        )
        version_id = uuid.uuid4().hex
        record["versions"].append({
            "version_id": version_id,
            "parent_version_id": record.get("active_version_id"),
            "content": "",
            "created_at": time.time(),
            "kind": "regeneration",
            "generation_id": generation["generation_id"],
            "idempotency_key": key,
            "request_hash": request_hash,
            "committed": False,
        })
        _write(path, record)
        heartbeat = generations.start_heartbeat(generation["generation_id"])
        view = _public(record)
        view["created"] = True
        view["version_id"] = version_id
        view["generation_id"] = generation["generation_id"]
        view["parent_version_id"] = record.get("active_version_id")
        view["_heartbeat"] = heartbeat
        return view


def commit_regeneration(
    session_id: str,
    user_id: str,
    message_id: str,
    version_id: str,
    content: str,
) -> dict:
    from orca.serve.conversations import MAX_MESSAGE_CHARS

    if not isinstance(content, str) or not content.strip():
        raise MessageVersionDenied("regeneration produced no text")
    if len(content) > MAX_MESSAGE_CHARS:
        content = content[:MAX_MESSAGE_CHARS]
    with _lock(session_id, message_id):
        path = _path(session_id, message_id)
        record = _read(path)
        if record is None:
            raise MessageVersionDenied("message version was not found")
        _check_owner(record, session_id, user_id)
        version = next((item for item in record["versions"] if item.get("version_id") == version_id), None)
        if version is None or version.get("kind") != "regeneration":
            raise MessageVersionDenied("regeneration version was not found")
        if version.get("committed"):
            view = _public(record)
            view["created"] = False
            view["version_id"] = version_id
            return view
        version["content"] = content
        version["committed"] = True
        record["active_version_id"] = version_id
        _write(path, record)
        view = _public(record)
        view["created"] = True
        view["version_id"] = version_id
        view["generation_id"] = version.get("generation_id")
        return view


def abort_regeneration(session_id: str, user_id: str, message_id: str, version_id: str) -> None:
    """Drop an uncommitted reservation. A committed version stays."""
    with _lock(session_id, message_id):
        path = _path(session_id, message_id)
        record = _read(path)
        if record is None:
            return
        _check_owner(record, session_id, user_id)
        kept = []
        changed = False
        for version in record["versions"]:
            if version.get("version_id") == version_id and not version.get("committed"):
                changed = True
                continue
            kept.append(version)
        if changed:
            record["versions"] = kept
            _write(path, record)


def delete_session(session_id: str) -> bool:
    try:
        directory = _dir(session_id)
    except MessageVersionDenied:
        return False
    removed = False
    for path in directory.glob("*"):
        try:
            path.unlink()
            removed = True
        except OSError:
            continue
    try:
        directory.rmdir()
    except OSError:
        pass
    return removed
