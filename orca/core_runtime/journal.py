"""Owner-scoped mission journal that survives a process restart.

Writes use O_NOFOLLOW, O_EXCL, and rename on a directory file descriptor.
A single-host flock serializes one machine. It is not multi-host durability.
``completed_verified`` is not a generic transition.
"""
from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import re
import secrets
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "orneur-local-mission/1"
_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_FIXED_DIRS = frozenset({"missions", "effects", "artifacts", "memory"})
_TERMINAL = frozenset({"completed_verified", "failed", "cancelled", "partial"})
_TRANSITIONS = {
    "draft": {"running", "cancelled"},
    "running": {"interrupted", "paused", "cancelled", "failed", "approval_required", "verifying", "revoked"},
    "interrupted": {"running", "failed", "cancelled", "revoked"},
    "paused": {"running", "cancelled", "revoked"},
    "approval_required": {"running", "cancelled", "failed", "revoked"},
    "verifying": {"failed", "partial", "uncertain", "cancelled", "revoked"},
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


def _directory_name(part: str) -> bool:
    return part in _FIXED_DIRS or bool(_ID.fullmatch(part))


def _file_name(part: str) -> bool:
    if part == "report.json":
        return True
    if part.endswith(".json") and _ID.fullmatch(part[:-5]):
        return True
    return False


class Journal:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise MissionError("symlink_refused")
        self._lock_path = self.root / ".lock"
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        try:
            probe = os.open(self.root, flags)
        except OSError as exc:
            raise MissionError("symlink_refused") from exc
        else:
            os.close(probe)

    @contextmanager
    def _exclusive(self):
        handle = open(self._lock_path, "a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    def _opendir(self, parts: tuple[str, ...]) -> int:
        try:
            fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError as exc:
            raise MissionError("symlink_refused") from exc
        for part in parts:
            if not _directory_name(part):
                os.close(fd)
                raise MissionError("path_escape")
            try:
                nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                try:
                    os.mkdir(part, dir_fd=fd)
                except FileExistsError:
                    pass
                try:
                    nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                except OSError as exc:
                    os.close(fd)
                    raise MissionError("symlink_refused") from exc
            except OSError as exc:
                os.close(fd)
                if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                    raise MissionError("symlink_refused") from exc
                raise MissionError("path_refused") from exc
            os.close(fd)
            fd = nxt
        return fd

    def _split(self, relative: Path) -> tuple[tuple[str, ...], str]:
        parts = relative.parts
        if not parts or any(part in {".", ".."} for part in parts):
            raise MissionError("path_escape")
        if not _file_name(parts[-1]) or not all(_directory_name(part) for part in parts[:-1]):
            raise MissionError("path_escape")
        return parts[:-1], parts[-1]

    def _read_bytes(self, relative: Path) -> bytes:
        directories, name = self._split(relative)
        fd = self._opendir(directories)
        try:
            try:
                file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                raise
            except OSError as exc:
                raise MissionError("symlink_refused") from exc
            try:
                chunks = []
                while True:
                    block = os.read(file_fd, 65536)
                    if not block:
                        break
                    chunks.append(block)
                    if sum(len(item) for item in chunks) > 1_000_000:
                        raise MissionError("input_too_large")
                return b"".join(chunks)
            finally:
                os.close(file_fd)
        finally:
            os.close(fd)

    def _write_bytes(self, relative: Path, data: bytes) -> None:
        if len(data) > 1_000_000:
            raise MissionError("input_too_large")
        directories, name = self._split(relative)
        fd = self._opendir(directories)
        tmp = f".{name}.{secrets.token_hex(8)}.tmp"
        try:
            file_fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            try:
                view = memoryview(data)
                while view:
                    written = os.write(file_fd, view)
                    view = view[written:]
                os.fsync(file_fd)
            finally:
                os.close(file_fd)
            os.rename(tmp, name, src_dir_fd=fd, dst_dir_fd=fd)
            os.fsync(fd)
        except OSError as exc:
            try:
                os.unlink(tmp, dir_fd=fd)
            except OSError:
                pass
            if exc.errno in {errno.ELOOP, errno.EEXIST}:
                raise MissionError("symlink_refused") from exc
            raise
        finally:
            os.close(fd)

    def _atomic(self, relative: Path, payload: dict) -> None:
        self._write_bytes(relative, json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())

    def _load(self, relative: Path) -> dict:
        return json.loads(self._read_bytes(relative))

    def _mission_rel(self, mission_id: str) -> Path:
        return Path("missions") / f"{mission_id}.json"

    def _effect_rel(self, mission_id: str, effect_key: str) -> Path:
        return Path("effects") / mission_id / f"{effect_key}.json"

    def _get_unlocked(self, mission_id: str, actor_user_id: str) -> dict:
        mission_id = _check_id(mission_id, "mission_id")
        _check_id(actor_user_id, "owner")
        try:
            record = self._load(self._mission_rel(mission_id))
        except FileNotFoundError:
            raise MissionHidden() from None
        if record.get("owner_user_id") != actor_user_id:
            raise MissionHidden()
        return record

    def _refusal_unlocked(self, record: dict) -> str | None:
        if record.get("access_revoked") or record.get("state") == "revoked":
            return "revoked_after_admission"
        if record.get("cancel_requested"):
            return "cancelled_after_admission"
        if record.get("state") in _TERMINAL:
            return "effect_refused"
        return None

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
            "actor_authenticated": False,
            "durability": "single_host_flock",
            "verification": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        with self._exclusive():
            try:
                self._load(self._mission_rel(mission_id))
            except FileNotFoundError:
                self._atomic(self._mission_rel(mission_id), record)
            else:
                raise MissionError("mission_exists")
        return record

    def get(self, mission_id: str, actor_user_id: str) -> dict:
        with self._exclusive():
            return self._get_unlocked(mission_id, actor_user_id)

    def transition(self, mission_id: str, actor_user_id: str, new_state: str) -> dict:
        if new_state == "completed_verified":
            raise MissionError("verification_required")
        with self._exclusive():
            record = self._get_unlocked(mission_id, actor_user_id)
            if record["access_revoked"] and new_state != "revoked":
                raise MissionError("revoked")
            allowed = _TRANSITIONS.get(record["state"], set())
            if new_state not in allowed:
                raise MissionError("illegal_transition")
            record["state"] = new_state
            record["updated_at"] = _now()
            self._atomic(self._mission_rel(mission_id), record)
            return record

    def seal_verified(self, mission_id: str, actor_user_id: str, *, input_bytes: bytes, total_cents: int) -> dict:
        """Bind the on-disk artifact to this input. Caller flags are ignored."""
        if type(total_cents) is not int or total_cents < 0:
            raise MissionError("verifier_rejected")
        mission_id = _check_id(mission_id, "mission_id")
        relative = Path("artifacts") / mission_id / "report.json"
        with self._exclusive():
            record = self._get_unlocked(mission_id, actor_user_id)
            refusal = self._refusal_unlocked(record)
            if refusal:
                raise MissionError(refusal)
            if record["state"] != "verifying":
                raise MissionError("verification_required")
            try:
                artifact = self._read_bytes(relative)
            except FileNotFoundError:
                raise MissionError("verifier_rejected") from None
            try:
                parsed = json.loads(artifact)
            except json.JSONDecodeError:
                raise MissionError("verifier_rejected") from None
            if parsed.get("mission_id") != mission_id or parsed.get("total_cents") != total_cents:
                raise MissionError("verifier_rejected")
            if parsed.get("verified") is not False:
                raise MissionError("verifier_rejected")
            record["state"] = "completed_verified"
            record["verification"] = {
                "verifier": "deterministic.recompute",
                "input_sha256": _sha(input_bytes),
                "artifact_sha256": _sha(artifact),
                "total_cents": total_cents,
            }
            record["updated_at"] = _now()
            self._atomic(self._mission_rel(mission_id), record)
            return record

    def request_cancel(self, mission_id: str, actor_user_id: str) -> dict:
        with self._exclusive():
            record = self._get_unlocked(mission_id, actor_user_id)
            if record["state"] in _TERMINAL or record["state"] == "revoked":
                return record
            record["cancel_requested"] = True
            record["updated_at"] = _now()
            self._atomic(self._mission_rel(mission_id), record)
            return record

    def revoke(self, mission_id: str, actor_user_id: str) -> dict:
        with self._exclusive():
            record = self._get_unlocked(mission_id, actor_user_id)
            record["access_revoked"] = True
            record["updated_at"] = _now()
            if record["state"] not in _TERMINAL and "revoked" in _TRANSITIONS.get(record["state"], set()):
                record["state"] = "revoked"
            self._atomic(self._mission_rel(mission_id), record)
            return record

    def mark_step(self, mission_id: str, actor_user_id: str, step_id: str, status: str) -> dict:
        with self._exclusive():
            record = self._get_unlocked(mission_id, actor_user_id)
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
            self._atomic(self._mission_rel(mission_id), record)
            return record

    def begin_effect(self, mission_id: str, actor_user_id: str, effect_key: str, payload: bytes) -> dict:
        effect_key = _check_id(effect_key, "effect")
        digest = _sha(payload)
        relative = self._effect_rel(mission_id, effect_key)
        with self._exclusive():
            record = self._get_unlocked(mission_id, actor_user_id)
            refusal = self._refusal_unlocked(record)
            try:
                existing = self._load(relative)
            except FileNotFoundError:
                existing = None
            if existing is not None:
                if existing["payload_sha256"] != digest:
                    raise MissionError("effect_conflict")
                existing["replay"] = True
                if refusal and existing.get("status") != "committed":
                    raise MissionError(refusal)
                return existing
            if refusal:
                raise MissionError("effect_refused")
            effect = {
                "schema": SCHEMA,
                "mission_id": mission_id,
                "effect_key": effect_key,
                "payload_sha256": digest,
                "status": "started",
                "writes": 0,
                "external_bytes_present": False,
                "external_outcome": "unconfirmed",
            }
            self._atomic(relative, effect)
            effect["replay"] = False
            return effect

    def note_write(self, mission_id: str, actor_user_id: str, effect_key: str) -> dict:
        relative = self._effect_rel(mission_id, _check_id(effect_key, "effect"))
        with self._exclusive():
            record = self._get_unlocked(mission_id, actor_user_id)
            effect = self._load(relative)
            if effect["status"] == "committed":
                effect["replay"] = True
                return effect
            refusal = self._refusal_unlocked(record)
            effect["caller_asserted_write"] = True
            effect["external_bytes_present"] = True
            effect["writes"] = int(effect["writes"]) + 1
            if refusal:
                effect["status"] = "not_committed"
                effect["reason"] = refusal
                effect["external_outcome"] = "unconfirmed"
                self._atomic(relative, effect)
                raise MissionError(refusal)
            effect["external_outcome"] = "local_file_only"
            effect["status"] = "bytes_written"
            self._atomic(relative, effect)
            effect["replay"] = False
            return effect

    def commit_effect(self, mission_id: str, actor_user_id: str, effect_key: str) -> dict:
        relative = self._effect_rel(mission_id, _check_id(effect_key, "effect"))
        with self._exclusive():
            record = self._get_unlocked(mission_id, actor_user_id)
            effect = self._load(relative)
            if effect["status"] == "committed":
                effect["replay"] = True
                return effect
            refusal = self._refusal_unlocked(record)
            if refusal:
                effect["status"] = "not_committed"
                effect["reason"] = refusal
                effect["external_outcome"] = "unconfirmed"
                self._atomic(relative, effect)
                raise MissionError(refusal)
            if effect["status"] not in {"started", "bytes_written"}:
                raise MissionError("effect_not_ready")
            effect["status"] = "committed"
            effect["external_outcome"] = "local_receipt_only"
            self._atomic(relative, effect)
            effect["replay"] = False
            return effect

    def effect(self, mission_id: str, actor_user_id: str, effect_key: str) -> dict | None:
        with self._exclusive():
            self._get_unlocked(mission_id, actor_user_id)
            try:
                return self._load(self._effect_rel(mission_id, _check_id(effect_key, "effect")))
            except FileNotFoundError:
                return None

    def write_bytes(self, relative: Path, data: bytes) -> None:
        with self._exclusive():
            self._write_bytes(relative, data)

    def read_bytes(self, relative: Path) -> bytes:
        with self._exclusive():
            return self._read_bytes(relative)

    def put_memory(self, *, memory_id: str, owner_user_id: str, body: dict, share_with: list[str]) -> dict:
        memory_id = _check_id(memory_id, "memory")
        owner_user_id = _check_id(owner_user_id, "owner")
        record = {
            "schema": SCHEMA,
            "memory_id": memory_id,
            "owner_user_id": owner_user_id,
            "body": body,
            "share_with": list(share_with),
            "expires_at": None,
            "actor_authenticated": False,
        }
        with self._exclusive():
            for mission_id in share_with:
                shared = self._get_unlocked(mission_id, owner_user_id)
                if shared["owner_user_id"] != owner_user_id:
                    raise MissionHidden()
            self._atomic(Path("memory") / owner_user_id / f"{memory_id}.json", record)
        return record

    def read_memory(self, *, memory_id: str, owner_user_id: str, actor_user_id: str, mission_id: str | None) -> dict:
        relative = Path("memory") / _check_id(owner_user_id, "owner") / f"{_check_id(memory_id, 'memory')}.json"
        with self._exclusive():
            try:
                record = self._load(relative)
            except FileNotFoundError:
                raise MissionHidden() from None
            if actor_user_id == record["owner_user_id"]:
                return record
            if mission_id and mission_id in record["share_with"]:
                mission = self._get_unlocked(mission_id, actor_user_id)
                if mission["owner_user_id"] == actor_user_id == record["owner_user_id"]:
                    return record
            raise MissionHidden()
