"""Owner pins, folders, and explicit share grants.

A pin does not change who can read a conversation. A share is a grant to
one account, with an expiry and a revocation flag. Holding a session id
is not a grant. The session message route stays closed to the grantee.
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

MIN_SHARE_TTL = 60
MAX_SHARE_TTL = 30 * 24 * 60 * 60
MAX_PINS = 200
MAX_FOLDERS = 50
MAX_FOLDER_SESSIONS = 200
_ID = re.compile(r"^[0-9a-f]{32}$")
_OWNER = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_NAME = re.compile(r"^[^\x00-\x1f]{1,80}$")


class OrganizationDenied(PermissionError):
    def __init__(self, reason: str, code: str = "organization_rejected"):
        self.reason = reason
        self.code = code
        super().__init__(reason)


def _root() -> Path:
    import orca.brain.memory as mem

    directory = Path(mem.MEMORY_DIR) / "organization"
    directory.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    return directory


def _owner_path(user_id: str) -> Path:
    if _OWNER.fullmatch(user_id or "") is None:
        raise OrganizationDenied("owner id is not valid")
    return _root() / f"{user_id}.json"


def _share_path(share_id: str) -> Path:
    if _ID.fullmatch(share_id or "") is None:
        raise OrganizationDenied("share id is not valid", "share_not_found")
    return _root() / "shares" / f"{share_id}.json"


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
def _lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path.with_suffix(".lock"), os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _blank(user_id: str) -> dict:
    return {"version": 1, "user_id": user_id, "pins": [], "folders": []}


def _load_owner(user_id: str) -> dict:
    record = _read(_owner_path(user_id))
    if record is None:
        return _blank(user_id)
    if record.get("user_id") != user_id:
        raise OrganizationDenied("organization record was not found")
    record.setdefault("pins", [])
    record.setdefault("folders", [])
    return record


def pins_for(user_id: str) -> list[str]:
    try:
        with _lock(_owner_path(user_id)):
            return list(_load_owner(user_id).get("pins") or [])
    except OrganizationDenied:
        return []


def pin(user_id: str, session_id: str) -> dict:
    with _lock(_owner_path(user_id)):
        record = _load_owner(user_id)
        pins = record["pins"]
        if session_id not in pins:
            if len(pins) >= MAX_PINS:
                raise OrganizationDenied("pin list is full", "pin_list_full")
            pins.append(session_id)
            _write(_owner_path(user_id), record)
        return {"session_id": session_id, "pinned": True}


def unpin(user_id: str, session_id: str) -> dict:
    with _lock(_owner_path(user_id)):
        record = _load_owner(user_id)
        record["pins"] = [item for item in record["pins"] if item != session_id]
        _write(_owner_path(user_id), record)
        return {"session_id": session_id, "pinned": False}


def folders_for(user_id: str) -> list[dict]:
    with _lock(_owner_path(user_id)):
        return list(_load_owner(user_id).get("folders") or [])


def create_folder(user_id: str, name: str) -> dict:
    if _NAME.fullmatch(name or "") is None:
        raise OrganizationDenied("folder name is not valid")
    with _lock(_owner_path(user_id)):
        record = _load_owner(user_id)
        if len(record["folders"]) >= MAX_FOLDERS:
            raise OrganizationDenied("folder list is full", "folder_list_full")
        folder = {"folder_id": uuid.uuid4().hex, "name": name, "session_ids": []}
        record["folders"].append(folder)
        _write(_owner_path(user_id), record)
        return folder


def add_to_folder(user_id: str, folder_id: str, session_id: str) -> dict:
    with _lock(_owner_path(user_id)):
        record = _load_owner(user_id)
        folder = next((item for item in record["folders"] if item.get("folder_id") == folder_id), None)
        if folder is None:
            raise OrganizationDenied("folder was not found", "folder_not_found")
        if session_id not in folder["session_ids"]:
            if len(folder["session_ids"]) >= MAX_FOLDER_SESSIONS:
                raise OrganizationDenied("folder is full", "folder_full")
            folder["session_ids"].append(session_id)
            _write(_owner_path(user_id), record)
        return folder


def _share_public(record: dict, *, now: float) -> dict:
    """Grant metadata. The session id stays on the server."""
    state = record.get("state")
    if state == "active" and now >= float(record.get("expires_at") or 0):
        state = "expired"
    return {
        "share_id": record.get("share_id"),
        "owner_id": record.get("owner_id"),
        "grantee_id": record.get("grantee_id"),
        "state": state,
        "expires_at": record.get("expires_at"),
        "created_at": record.get("created_at"),
    }


def create_share(owner_id: str, session_id: str, grantee_id: str, ttl_seconds: int, *, now: float | None = None) -> dict:
    from orca.auth.store import get_user_by_id

    if owner_id == grantee_id:
        raise OrganizationDenied("a share cannot name its owner", "share_rejected")
    if get_user_by_id(grantee_id) is None:
        raise OrganizationDenied("grantee was not found", "share_not_found")
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not MIN_SHARE_TTL <= ttl_seconds <= MAX_SHARE_TTL:
        raise OrganizationDenied("share ttl is not valid", "share_rejected")
    from orca.serve import temporary_chat

    if temporary_chat.is_active(session_id):
        raise OrganizationDenied("temporary chats cannot be shared", "temporary_not_shareable")
    moment = time.time() if now is None else now
    share_id = uuid.uuid4().hex
    record = {
        "version": 1,
        "share_id": share_id,
        "session_id": session_id,
        "owner_id": owner_id,
        "grantee_id": grantee_id,
        "state": "active",
        "created_at": moment,
        "expires_at": moment + ttl_seconds,
        "revoked": False,
    }
    path = _share_path(share_id)
    with _lock(path):
        _write(path, record)
    return _share_public(record, now=moment)


def _load_share(share_id: str, caller_id: str, *, now: float) -> dict:
    path = _share_path(share_id)
    record = _read(path)
    if record is None or caller_id not in {record.get("owner_id"), record.get("grantee_id")}:
        raise OrganizationDenied("share was not found", "share_not_found")
    if record.get("revoked") or record.get("state") == "revoked":
        record["state"] = "revoked"
        return record
    if now >= float(record.get("expires_at") or 0):
        record["state"] = "expired"
        _write(path, record)
        return record
    record["state"] = "active"
    return record


def revoke_share(share_id: str, owner_id: str, *, now: float | None = None) -> dict:
    moment = time.time() if now is None else now
    path = _share_path(share_id)
    with _lock(path):
        record = _read(path)
        if record is None or record.get("owner_id") != owner_id:
            raise OrganizationDenied("share was not found", "share_not_found")
        record["revoked"] = True
        record["state"] = "revoked"
        _write(path, record)
        return _share_public(record, now=moment)


def share_session_for_reader(share_id: str, caller_id: str, *, now: float | None = None) -> str:
    """Return the session id only when this caller may read through the grant."""
    moment = time.time() if now is None else now
    path = _share_path(share_id)
    with _lock(path):
        record = _load_share(share_id, caller_id, now=moment)
        if record.get("state") != "active":
            raise OrganizationDenied("share is not active", "share_not_active")
        return str(record["session_id"])


def describe_share(share_id: str, caller_id: str, *, now: float | None = None) -> dict:
    moment = time.time() if now is None else now
    path = _share_path(share_id)
    with _lock(path):
        record = _load_share(share_id, caller_id, now=moment)
        if record.get("state") != "active":
            raise OrganizationDenied("share is not active", "share_not_active")
        return _share_public(record, now=moment)


def _shares_dir() -> Path:
    return _root() / "shares"


def revoke_session(session_id: str, *, now: float | None = None) -> int:
    """Stop every grant for this conversation. Used when it is deleted or becomes temporary."""
    directory = _shares_dir()
    if not directory.exists():
        return 0
    moment = time.time() if now is None else now
    stopped = 0
    for path in directory.glob("*.json"):
        with _lock(path):
            record = _read(path)
            if not isinstance(record, dict) or record.get("session_id") != session_id:
                continue
            if record.get("revoked") or record.get("state") == "revoked":
                continue
            record["revoked"] = True
            record["state"] = "revoked"
            record["revoked_at"] = moment
            _write(path, record)
            stopped += 1
    return stopped


def forget_session(user_id: str, session_id: str) -> None:
    """Drop a deleted conversation from this owner's pins and folders."""
    try:
        path = _owner_path(user_id)
    except OrganizationDenied:
        return
    with _lock(path):
        record = _load_owner(user_id)
        pins = [item for item in record["pins"] if item != session_id]
        changed = pins != record["pins"]
        record["pins"] = pins
        for folder in record["folders"]:
            kept = [item for item in folder.get("session_ids") or [] if item != session_id]
            if kept != folder.get("session_ids"):
                folder["session_ids"] = kept
                changed = True
        if changed:
            _write(path, record)


def drop_owner(user_id: str, *, now: float | None = None) -> None:
    """Account deletion: remove pin metadata and stop grants this account owns or holds."""
    moment = time.time() if now is None else now
    directory = _shares_dir()
    if directory.exists():
        for path in directory.glob("*.json"):
            with _lock(path):
                record = _read(path)
                if not isinstance(record, dict):
                    continue
                if user_id not in {record.get("owner_id"), record.get("grantee_id")}:
                    continue
                if record.get("revoked") or record.get("state") == "revoked":
                    continue
                record["revoked"] = True
                record["state"] = "revoked"
                record["revoked_at"] = moment
                _write(path, record)
    try:
        path = _owner_path(user_id)
    except OrganizationDenied:
        return
    with _lock(path):
        if path.exists():
            path.unlink()


def incoming_shares(grantee_id: str, *, now: float | None = None) -> list[dict]:
    moment = time.time() if now is None else now
    found = []
    directory = _root() / "shares"
    if not directory.exists():
        return []
    for path in directory.glob("*.json"):
        record = _read(path)
        if not isinstance(record, dict) or record.get("grantee_id") != grantee_id:
            continue
        if record.get("revoked"):
            continue
        view = _share_public(record, now=moment)
        if view["state"] == "active":
            found.append(view)
    return found
