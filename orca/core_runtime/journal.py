"""Owner-scoped mission journal that survives a process restart.

Writes are atomic and serialized with a single-host flock. A terminal
state is not replaced. The same effect key does not run its writer twice
after the artifact bytes are already on disk.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "orneur-local-mission/1"
_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_TERMINAL = frozenset({"completed_verified", "failed", "cancelled", "partial"})
_TRANSITIONS = {
    "draft": {"running", "cancelled"},
    "running": {"interrupted", "paused", "cancelled", "failed", "approval_required", "verifying", "revoked"},
    "interrupted": {"running", "failed", "cancelled", "revoked"},
    "paused": {"running", "cancelled", "revoked"},
    "approval_required": {"running", "cancelled", "failed", "revoked"},
    "verifying": {"completed_verified", "failed", "partial", "uncertain"},
    "uncertain": {"running", "failed", "cancelled", "revoked"},
    "revoked": set(),
    "completed_verified": set(),
    "failed": set(),
    "cancelled": set(),
    "partial": set(),
}


class MissionError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class MissionHidden(MissionError):
    def __init__(self):
        super().__init__("not_found")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _check_id(value: str, label: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise MissionError(f"invalid_{label}")
    return value


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Journal:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock_path = self.root / ".lock"

    @contextmanager
    def _exclusive(self):
        handle = open(self._lock_path, "a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    def _atomic(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise MissionError("symlink_refused")
        temporary = path.with_name(path.name + ".tmp")
        if temporary.is_symlink():
            raise MissionError("symlink_refused")
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)

    def _read(self, path: Path) -> dict:
        if path.is_symlink():
            raise MissionError("symlink_refused")
        return json.loads(path.read_text(encoding="utf-8"))

    def _mission_path(self, mission_id: str) -> Path:
        return self.root / "missions" / f"{mission_id}.json"

    def _effect_path(self, mission_id: str, effect_key: str) -> Path:
        return self.root / "effects" / mission_id / f"{effect_key}.json"

    def create(self, *, mission_id: str, owner_user_id: str, objective: dict, steps: list[str]) -> dict:
        mission_id = _check_id(mission_id, "mission_id")
        owner_user_id = _check_id(owner_user_id, "owner")
        if not isinstance(objective, dict) or objective.get("kind") != "structured_report":
            raise MissionError("objective_not_structured")
        if not steps or any(not _ID.fullmatch(step) for step in steps):
            raise MissionError("invalid_step")
        record = {
            "schema": SCHEMA,
            "mission_id": mission_id,
            "owner_user_id": owner_user_id,
            "state": "draft",
            "objective": objective,
            "steps": [{"id": step, "status": "pending"} for step in steps],
            "cancel_requested": False,
            "access_revoked": False,
            "created_at": _now(),
            "updated_at": _now(),
        }
        with self._exclusive():
            path = self._mission_path(mission_id)
            if path.exists():
                raise MissionError("mission_exists")
            self._atomic(path, record)
        return record

    def get(self, mission_id: str, actor_user_id: str) -> dict:
        mission_id = _check_id(mission_id, "mission_id")
        _check_id(actor_user_id, "owner")
        path = self._mission_path(mission_id)
        if not path.exists():
            raise MissionHidden()
        record = self._read(path)
        if record.get("owner_user_id") != actor_user_id:
            raise MissionHidden()
        return record

    def transition(self, mission_id: str, actor_user_id: str, new_state: str) -> dict:
        with self._exclusive():
            record = self.get(mission_id, actor_user_id)
            if record["access_revoked"] and new_state != "revoked":
                raise MissionError("revoked")
            allowed = _TRANSITIONS.get(record["state"], set())
            if new_state not in allowed:
                raise MissionError("illegal_transition")
            record["state"] = new_state
            record["updated_at"] = _now()
            self._atomic(self._mission_path(mission_id), record)
            return record

    def request_cancel(self, mission_id: str, actor_user_id: str) -> dict:
        with self._exclusive():
            record = self.get(mission_id, actor_user_id)
            if record["state"] in _TERMINAL or record["state"] == "revoked":
                return record
            record["cancel_requested"] = True
            record["updated_at"] = _now()
            self._atomic(self._mission_path(mission_id), record)
            return record

    def revoke(self, mission_id: str, actor_user_id: str) -> dict:
        with self._exclusive():
            record = self.get(mission_id, actor_user_id)
            record["access_revoked"] = True
            record["updated_at"] = _now()
            if record["state"] not in _TERMINAL:
                if "revoked" in _TRANSITIONS.get(record["state"], set()):
                    record["state"] = "revoked"
            self._atomic(self._mission_path(mission_id), record)
            return record

    def mark_step(self, mission_id: str, actor_user_id: str, step_id: str, status: str) -> dict:
        with self._exclusive():
            record = self.get(mission_id, actor_user_id)
            if record["access_revoked"] or record["state"] in _TERMINAL | {"revoked"}:
                raise MissionError("mission_closed")
            found = False
            for step in record["steps"]:
                if step["id"] == step_id:
                    step["status"] = status
                    found = True
            if not found:
                raise MissionError("unknown_step")
            record["updated_at"] = _now()
            self._atomic(self._mission_path(mission_id), record)
            return record

    def begin_effect(self, mission_id: str, actor_user_id: str, effect_key: str, payload: bytes) -> dict:
        effect_key = _check_id(effect_key, "effect")
        digest = _sha(payload)
        with self._exclusive():
            record = self.get(mission_id, actor_user_id)
            if record["access_revoked"] or record["cancel_requested"] or record["state"] in _TERMINAL | {"revoked"}:
                raise MissionError("effect_refused")
            path = self._effect_path(mission_id, effect_key)
            if path.exists():
                existing = self._read(path)
                if existing["payload_sha256"] != digest:
                    raise MissionError("effect_conflict")
                existing["replay"] = True
                return existing
            effect = {
                "schema": SCHEMA,
                "mission_id": mission_id,
                "effect_key": effect_key,
                "payload_sha256": digest,
                "status": "started",
                "writes": 0,
            }
            self._atomic(path, effect)
            effect["replay"] = False
            return effect

    def note_write(self, mission_id: str, actor_user_id: str, effect_key: str) -> dict:
        with self._exclusive():
            self.get(mission_id, actor_user_id)
            path = self._effect_path(mission_id, effect_key)
            effect = self._read(path)
            if effect["status"] == "committed":
                effect["replay"] = True
                return effect
            effect["writes"] = int(effect["writes"]) + 1
            effect["status"] = "bytes_written"
            self._atomic(path, effect)
            effect["replay"] = False
            return effect

    def commit_effect(self, mission_id: str, actor_user_id: str, effect_key: str) -> dict:
        with self._exclusive():
            self.get(mission_id, actor_user_id)
            path = self._effect_path(mission_id, effect_key)
            effect = self._read(path)
            if effect["status"] == "committed":
                effect["replay"] = True
                return effect
            if effect["status"] not in {"started", "bytes_written"}:
                raise MissionError("effect_not_ready")
            effect["status"] = "committed"
            self._atomic(path, effect)
            effect["replay"] = False
            return effect

    def effect(self, mission_id: str, actor_user_id: str, effect_key: str) -> dict | None:
        self.get(mission_id, actor_user_id)
        path = self._effect_path(mission_id, effect_key)
        if not path.exists():
            return None
        return self._read(path)

    def put_memory(self, *, memory_id: str, owner_user_id: str, body: dict, share_with: list[str]) -> dict:
        memory_id = _check_id(memory_id, "memory")
        owner_user_id = _check_id(owner_user_id, "owner")
        for mission_id in share_with:
            _check_id(mission_id, "mission_id")
        record = {
            "schema": SCHEMA,
            "memory_id": memory_id,
            "owner_user_id": owner_user_id,
            "body": body,
            "share_with": list(share_with),
            "expires_at": None,
        }
        with self._exclusive():
            self._atomic(self.root / "memory" / owner_user_id / f"{memory_id}.json", record)
        return record

    def read_memory(self, *, memory_id: str, owner_user_id: str, actor_user_id: str, mission_id: str | None) -> dict:
        path = self.root / "memory" / _check_id(owner_user_id, "owner") / f"{_check_id(memory_id, 'memory')}.json"
        if not path.exists() or path.is_symlink():
            raise MissionHidden()
        record = self._read(path)
        if actor_user_id == record["owner_user_id"]:
            return record
        if mission_id and mission_id in record["share_with"]:
            mission = self.get(mission_id, actor_user_id)
            if mission["owner_user_id"] == actor_user_id:
                return record
        raise MissionHidden()
