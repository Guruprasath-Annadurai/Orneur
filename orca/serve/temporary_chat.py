"""Server-owned temporary chat.

A normal session has no record here. Opening one checks the policy, then
publishes `active` with an expiry. The record contains no message text.

`expired` and `closed` are written only after the conversation cascade
has removed the transcript. A failed deletion stays `failed` and is not
reported as expired or closed.
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

MIN_TTL_SECONDS = 60
MAX_TTL_SECONDS = 24 * 60 * 60
_TERMINAL = {"expired", "closed", "failed"}
_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class TemporaryChatDenied(PermissionError):
    def __init__(self, reason: str, code: str = "temporary_rejected"):
        self.reason = reason
        self.code = code
        super().__init__(reason)


def _dir() -> Path:
    import orca.brain.memory as mem

    directory = Path(mem.MEMORY_DIR) / "temporary_chats"
    directory.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    return directory


def _path(session_id: str) -> Path:
    if _SESSION_ID.fullmatch(session_id or "") is None:
        raise TemporaryChatDenied("session id is not valid")
    return _dir() / f"{session_id}.json"


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
def _lock(session_id: str):
    path = _path(session_id)
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
    state = record.get("state")
    view = {
        "session_id": record.get("session_id"),
        "state": state,
        "ttl_seconds": record.get("ttl_seconds"),
        "activated_at": record.get("activated_at"),
        "expires_at": record.get("expires_at"),
        "terminal": state in _TERMINAL,
        "reason": record.get("reason"),
        "transitions": list(record.get("transitions") or []),
    }
    if isinstance(record.get("remaining"), list):
        view["remaining"] = list(record["remaining"])
    if isinstance(record.get("intended_state"), str):
        view["intended_state"] = record["intended_state"]
    return view


def read(session_id: str, user_id: str) -> dict | None:
    """The caller's tombstone, or None when this session was never temporary.

    A tombstone owned by someone else raises, so the caller cannot tell a
    missing session from another account's temporary chat.
    """
    try:
        path = _path(session_id)
    except TemporaryChatDenied:
        return None
    record = _read(path)
    if record is None:
        return None
    if record.get("user_id") != user_id:
        raise TemporaryChatDenied("temporary chat was not found", "temporary_not_found")
    return _public(record)


def is_active(session_id: str, *, now: float | None = None) -> bool:
    try:
        record = _read(_path(session_id))
    except TemporaryChatDenied:
        return False
    if record is None or record.get("state") != "active":
        return False
    moment = time.time() if now is None else now
    return moment < float(record.get("expires_at") or 0)


def is_hidden(session_id: str) -> bool:
    """Active temporary chats stay out of history list and search."""
    return is_active(session_id)


def activate(session_id: str, user_id: str, ttl_seconds: int, *, now: float | None = None) -> dict:
    if not isinstance(user_id, str) or not user_id:
        raise TemporaryChatDenied("temporary chat requires a signed-in owner", "temporary_rejected")
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int):
        raise TemporaryChatDenied("temporary chat ttl is not valid", "temporary_rejected")
    if not MIN_TTL_SECONDS <= ttl_seconds <= MAX_TTL_SECONDS:
        raise TemporaryChatDenied("temporary chat ttl is not valid", "temporary_rejected")
    moment = time.time() if now is None else now
    with _lock(session_id):
        path = _path(session_id)
        existing = _read(path)
        if existing is not None:
            if existing.get("user_id") != user_id:
                raise TemporaryChatDenied("temporary chat was not found", "temporary_not_found")
            if existing.get("state") == "active" and moment < float(existing.get("expires_at") or 0):
                view = _public(existing)
                view["created"] = False
                return view
            if existing.get("state") in _TERMINAL:
                raise TemporaryChatDenied("temporary chat is already finished", "temporary_finished")
        from orca.serve import conversations

        if conversations.last_activity(session_id) is not None and not (
            existing is not None and existing.get("state") == "active"
        ):
            raise TemporaryChatDenied("temporary chat cannot adopt an existing transcript", "temporary_not_empty")
        from orca.serve import organization

        organization.revoke_session(session_id, now=moment)
        record = {
            "version": 1,
            "session_id": session_id,
            "user_id": user_id,
            "state": "active",
            "ttl_seconds": ttl_seconds,
            "activated_at": moment,
            "expires_at": moment + ttl_seconds,
            "reason": None,
            "transitions": [
                {"state": "policy_check", "at": moment},
                {"state": "activation_pending", "at": moment},
                {"state": "active", "at": moment},
            ],
        }
        _write(path, record)
        view = _public(record)
        view["created"] = True
        return view


def _transcript_gone(session_id: str) -> bool:
    from orca.serve import conversations

    try:
        return conversations.last_activity(session_id) is None
    except Exception:
        return False


def _delete_contents(session_id: str, user_id: str) -> dict:
    from orca.serve import generations
    from orca.serve.account_delete import _delete_session_data, _remove_session_title
    from orca.auth.store import release_session
    import sys

    result = _delete_session_data(session_id)
    if not isinstance(result, dict):
        result = {}
    generations.delete_for_session(session_id, user_id)
    _remove_session_title(session_id)
    live = getattr(sys.modules.get("orca.serve.api"), "_sessions", None)
    if isinstance(live, dict):
        live.pop(session_id, None)
    release_session(session_id, user_id)
    try:
        from orca.serve.authorized_product_index import revoke
        revoke(user_id, session_id)
        result["authorized_binding_revoke_attempted"] = True
    except Exception:
        result["authorized_binding_error"] = "revoke_failed"
    return result


def _remaining_evidence(session_id: str, user_id: str, delete_result: dict | None = None) -> list[dict]:
    """Re-read the stores a closure has to clear.

    A store that cannot be read is remaining evidence. Age is not used.
    An authorized binding that still exists is remaining: revocation does
    not prove the index bytes are gone. An 8-character keyword file with
    bytes is remaining because its owner is not certain.
    """
    import orca.brain.memory as mem
    import orca.config as orca_config

    found: list[dict] = []
    result = delete_result if isinstance(delete_result, dict) else {}
    for key in result:
        if isinstance(key, str) and key.endswith("_error"):
            found.append({
                "store": key[: -len("_error")],
                "detail": "cleanup reported an error and this store was not proven empty",
            })
    if not _transcript_gone(session_id):
        found.append({"store": "transcript", "detail": "the conversation transcript is still present or could not be read"})
    versions = Path(mem.MEMORY_DIR) / "message_versions" / session_id
    try:
        if versions.exists():
            leftovers = [path.name for path in versions.iterdir() if path.name.endswith(".json") or path.is_symlink()]
            if leftovers:
                found.append({"store": "message_versions", "detail": "message version files remain"})
    except OSError:
        found.append({"store": "message_versions", "detail": "message versions could not be read"})
    try:
        from orca.docs.store import DOCS_DIR, list_docs
        docs = list_docs(session_id)
        if docs:
            found.append({"store": "documents", "detail": "the document registry still lists this session"})
        fallback = Path(DOCS_DIR) / f"kw_{session_id[:8]}.jsonl"
        if fallback.is_symlink() or (fallback.exists() and fallback.stat().st_size > 0):
            found.append({
                "store": "keyword_fallback",
                "detail": "a keyword fallback still has bytes; an 8-character prefix does not prove which session owns it",
            })
    except Exception:
        found.append({"store": "documents", "detail": "document stores could not be read"})
    episodes = Path(mem.MEMORY_DIR) / "episodes" / f"{session_id}.json"
    if episodes.exists():
        found.append({"store": "episodic_memory", "detail": "the episodic memory file remains"})
    generation_dir = Path(mem.MEMORY_DIR) / "generations"
    if generation_dir.exists():
        try:
            for path in generation_dir.glob("*.json"):
                if path.is_symlink():
                    found.append({"store": "generations", "detail": "a generation symlink was not followed"})
                    break
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError):
                    found.append({"store": "generations", "detail": "a generation record could not be read"})
                    break
                if isinstance(payload, dict) and payload.get("session_id") == session_id and payload.get("user_id") in (user_id, None):
                    found.append({"store": "generations", "detail": "a generation record for this session remains"})
                    break
        except OSError:
            found.append({"store": "generations", "detail": "generation records could not be read"})
    import sys
    live = getattr(sys.modules.get("orca.serve.api"), "_sessions", None)
    if isinstance(live, dict) and session_id in live:
        found.append({"store": "live_session", "detail": "this process still holds the session"})
    titles = getattr(sys.modules.get("orca.serve.api"), "_session_titles", None)
    if isinstance(titles, dict) and session_id in titles:
        found.append({"store": "session_title", "detail": "the live session title remains"})
    title_path = Path(orca_config.ORCA_HOME) / "session_titles.json"
    try:
        if title_path.is_file() and not title_path.is_symlink():
            stored_titles = json.loads(title_path.read_text(encoding="utf-8"))
            if isinstance(stored_titles, dict) and session_id in stored_titles:
                found.append({"store": "session_title", "detail": "the stored session title remains"})
    except (OSError, UnicodeError, json.JSONDecodeError):
        found.append({"store": "session_title", "detail": "session titles could not be read"})
    try:
        binding = Path(orca_config.ORCA_HOME) / "authorized_index" / user_id / "bindings" / f"{session_id}.json"
        if binding.exists():
            found.append({
                "store": "authorized_binding",
                "detail": "an authorized retrieval binding still exists; revocation does not prove the index bytes are gone",
            })
    except OSError:
        found.append({"store": "authorized_binding", "detail": "the authorized binding could not be read"})
    return found


def _closure_view(record: dict, *, deleted: bool, retried: bool | None = None) -> dict:
    view = _public(record)
    view["deleted"] = deleted
    view["remaining"] = list(record.get("remaining") or [])
    if retried is not None:
        view["retried"] = retried
    return view


def finish(session_id: str, user_id: str, final_state: str, *, now: float | None = None) -> dict:
    """Delete the conversation, then store `closed` or `expired`.

    The state file is not changed to that terminal word until the
    transcript is gone. A deletion that leaves the transcript stores
    `failed` instead.
    """
    if final_state not in {"closed", "expired"}:
        raise TemporaryChatDenied("temporary chat final state is not valid")
    moment = time.time() if now is None else now
    with _lock(session_id):
        path = _path(session_id)
        record = _read(path)
        if record is None or record.get("user_id") != user_id:
            raise TemporaryChatDenied("temporary chat was not found", "temporary_not_found")
        if record.get("state") in _TERMINAL:
            return _public(record)
        record["intended_state"] = final_state
        record["transitions"] = list(record.get("transitions") or []) + [{"state": "closing", "at": moment}]
        _write(path, record)
        try:
            delete_result = _delete_contents(session_id, user_id)
        except Exception:
            delete_result = {"deletion_error": "cleanup_raised"}
        evidence = _remaining_evidence(session_id, user_id, delete_result if isinstance(delete_result, dict) else {})
        if evidence:
            record["state"] = "failed"
            record["reason"] = "deletion_incomplete"
            record["remaining"] = evidence
            record["transitions"].append({"state": "failed", "at": time.time()})
            _write(path, record)
            return _closure_view(record, deleted=False)
        record["state"] = final_state
        record["reason"] = final_state
        record["remaining"] = []
        record["transitions"].append({"state": final_state, "at": time.time()})
        _write(path, record)
        return _closure_view(record, deleted=True)


def retry_failed_closure(session_id: str, user_id: str) -> dict:
    """Retry a failed temporary-chat deletion for the same owner.

    A missing intended state is not guessed. The chat is not reopened.
    """
    with _lock(session_id):
        path = _path(session_id)
        record = _read(path)
        if record is None or record.get("user_id") != user_id:
            raise TemporaryChatDenied("temporary chat was not found", "temporary_not_found")
        if record.get("state") != "failed":
            return _closure_view(record, deleted=record.get("state") in {"closed", "expired"}, retried=False)
        intended = record.get("intended_state")
        if intended not in {"closed", "expired"}:
            record["remaining"] = list(record.get("remaining") or [])
            view = _closure_view(record, deleted=False, retried=False)
            view["reason"] = "intended closure was not recorded"
            return view
        try:
            delete_result = _delete_contents(session_id, user_id)
        except Exception:
            delete_result = {"deletion_error": "cleanup_raised"}
        evidence = _remaining_evidence(session_id, user_id, delete_result if isinstance(delete_result, dict) else {})
        if evidence:
            record["remaining"] = evidence
            record["reason"] = "deletion_incomplete"
            _write(path, record)
            return _closure_view(record, deleted=False, retried=True)
        record["state"] = intended
        record["reason"] = intended
        record["remaining"] = []
        record["transitions"] = list(record.get("transitions") or []) + [{"state": intended, "at": time.time()}]
        _write(path, record)
        return _closure_view(record, deleted=True, retried=True)


def enforce(session_id: str, *, now: float | None = None) -> dict | None:
    """Expire a due temporary chat. Returns a refusal when the caller must stop.

    `None` means the session is not a finished temporary chat. An active,
    unexpired temporary chat also returns None so the turn can proceed.
    """
    try:
        path = _path(session_id)
    except TemporaryChatDenied:
        return None
    record = _read(path)
    if record is None:
        return None
    moment = time.time() if now is None else now
    state = record.get("state")
    user_id = record.get("user_id")
    if state == "active" and moment >= float(record.get("expires_at") or 0) and isinstance(user_id, str):
        finished = finish(session_id, user_id, "expired", now=moment)
        return {
            "error": "temporary chat has expired",
            "code": "temporary_expired" if finished.get("state") == "expired" else "temporary_deletion_incomplete",
            "state": finished.get("state"),
            "user_id": user_id,
        }
    if state == "expired":
        return {"error": "temporary chat has expired", "code": "temporary_expired", "state": state, "user_id": user_id}
    if state == "closed":
        return {"error": "temporary chat is closed", "code": "temporary_closed", "state": state, "user_id": user_id}
    if state == "failed":
        return {"error": "temporary chat could not be deleted", "code": "temporary_deletion_incomplete", "state": state, "user_id": user_id}
    return None


def expire_due(*, now: float | None = None) -> dict:
    moment = time.time() if now is None else now
    expired, failed = [], []
    for path in list(_dir().glob("*.json")):
        record = _read(path)
        if not isinstance(record, dict) or record.get("state") != "active":
            continue
        if moment < float(record.get("expires_at") or 0):
            continue
        session_id = record.get("session_id")
        user_id = record.get("user_id")
        if not isinstance(session_id, str) or not isinstance(user_id, str):
            continue
        finished = finish(session_id, user_id, "expired", now=moment)
        if finished.get("state") == "expired":
            expired.append(session_id)
        else:
            failed.append(session_id)
    return {"expired": expired, "failed": failed}
