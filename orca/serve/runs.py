"""One correlation id for concurrent generations.

A run does not grant access to a conversation. The caller must already
own each session. Another account cannot read or extend the run.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

MAX_MEMBERS = 100
_ID = re.compile(r"^[0-9a-f]{32}$")


class RunDenied(PermissionError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _dir() -> Path:
    import orca.brain.memory as mem

    directory = Path(mem.MEMORY_DIR) / "runs"
    directory.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    return directory


def _path(run_id: str) -> Path:
    if _ID.fullmatch(run_id or "") is None:
        raise RunDenied("run id is not valid")
    return _dir() / f"{run_id}.json"


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


def _read(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


@contextmanager
def _lock(run_id: str):
    path = _path(run_id)
    fd = os.open(path.with_suffix(".lock"), os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield path
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _public(record: dict) -> dict:
    members = [
        {"generation_id": item.get("generation_id"), "session_id": item.get("session_id"), "attached_at": item.get("attached_at")}
        for item in record.get("members") or []
        if isinstance(item, dict)
    ]
    return {
        "run_id": record.get("run_id"),
        "created_at": record.get("created_at"),
        "members": members,
        "count": len(members),
    }


def create(user_id: str) -> dict:
    if not isinstance(user_id, str) or not user_id:
        raise RunDenied("run requires a signed-in owner")
    run_id = uuid.uuid4().hex
    record = {
        "version": 1,
        "run_id": run_id,
        "user_id": user_id,
        "created_at": time.time(),
        "members": [],
    }
    with _lock(run_id):
        _write(_path(run_id), record)
    return _public(record)


def read(run_id: str, user_id: str) -> dict:
    with _lock(run_id):
        record = _read(_path(run_id))
    if record is None or record.get("user_id") != user_id:
        raise RunDenied("run was not found")
    return _public(record)


def require_owner(run_id: str, user_id: str) -> dict:
    return read(run_id, user_id)


def attach(run_id: str, user_id: str, generation_id: str, session_id: str) -> dict:
    if not isinstance(generation_id, str) or _ID.fullmatch(generation_id) is None:
        raise RunDenied("generation id is not valid")
    with _lock(run_id):
        path = _path(run_id)
        record = _read(path)
        if record is None or record.get("user_id") != user_id:
            raise RunDenied("run was not found")
        members = record.setdefault("members", [])
        for item in members:
            if item.get("generation_id") == generation_id:
                return _public(record)
        if len(members) >= MAX_MEMBERS:
            raise RunDenied("run is full")
        members.append({
            "generation_id": generation_id,
            "session_id": session_id,
            "attached_at": time.time(),
        })
        _write(path, record)
        return _public(record)
