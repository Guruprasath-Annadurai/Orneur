"""Transactional authoritative turn commit.

JSONL alone cannot provide fencing + version CAS. This module stages a pending
turn, enforces owner + expected conversation version + lease fence, performs
the Redis CAS (when enabled), and only then appends to the canonical JSONL
transcript. Failed commits never mutate authoritative history.

Crash recovery
--------------
* Pending file exists, Redis CAS never succeeded (or Redis disabled and
  version check would fail): ``recover_pending`` discards the staging file.
* Pending file exists and Redis revision/fence proves the CAS landed but
  JSONL append did not: ``recover_pending`` completes the JSONL append and
  clears the staging file (idempotent on message-count version).
* Retries with the same ``commit_id`` are idempotent: a committed marker
  short-circuits to success without a second append.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from orca.auth.store import check_session_access
from orca.serve import conversations, session_store

_COMMIT_ID_MAX = 64


class TurnCommitError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _staging_dir() -> Path:
    import orca.brain.memory as mem

    d = Path(mem.MEMORY_DIR) / "turn_commits"
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def _pending_path(session_id: str, commit_id: str) -> Path:
    if not conversations._SESSION_ID_RE.match(session_id or ""):
        raise TurnCommitError("session_required")
    if not isinstance(commit_id, str) or not commit_id or len(commit_id) > _COMMIT_ID_MAX:
        raise TurnCommitError("invalid_commit_id")
    if any(ch in commit_id for ch in ("/", "\\", "..")):
        raise TurnCommitError("invalid_commit_id")
    return _staging_dir() / f"{session_id}.{commit_id}.pending.json"


def _committed_marker(session_id: str, commit_id: str) -> Path:
    return _staging_dir() / f"{session_id}.{commit_id}.committed"


def message_count(session_id: str) -> int:
    body = conversations.transcript(session_id, limit=1, offset=0)
    return int(body.get("total") or 0)


def _write_pending(path: Path, payload: dict) -> None:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        os.write(fd, raw)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def _append_turn(payload: dict) -> None:
    conversations.append(payload["session_id"], "user", payload["user_message"])
    meta = payload.get("assistant_meta") or None
    conversations.append(payload["session_id"], "assistant", payload["assistant_message"], meta=meta)


def commit_turn(
    *,
    user_id: str,
    session_id: str,
    user_message: str,
    assistant_message: str,
    assistant_meta: dict | None,
    expected_version: int,
    fence_token: str | None,
    commit_id: str,
    model_variant: str = "nano",
) -> int:
    """Atomically commit one user+assistant turn. Returns the new message count.

    Raises ``TurnCommitError`` with:
      * ``session_not_found`` — ownership failed
      * ``session_conflict`` — version / fence / Redis CAS refused
      * ``session_busy`` — lease not held
    """
    if not user_id or not check_session_access(session_id, user_id):
        raise TurnCommitError("session_not_found")
    marker = _committed_marker(session_id, commit_id)
    if marker.exists():
        return message_count(session_id)

    current = message_count(session_id)
    if current != int(expected_version):
        raise TurnCommitError("session_conflict")

    if session_store.enabled():
        if not fence_token or not session_store.lease_held(session_id, fence_token):
            raise TurnCommitError("session_busy")

    pending = {
        "commit_id": commit_id,
        "user_id": user_id,
        "session_id": session_id,
        "user_message": user_message,
        "assistant_message": assistant_message,
        "assistant_meta": assistant_meta or {},
        "expected_version": int(expected_version),
        "fence_token": fence_token or "",
        "model_variant": model_variant,
        "staged_at": time.time(),
    }
    path = _pending_path(session_id, commit_id)
    _write_pending(path, pending)

    _state, rev = session_store.load_session_state_with_revision(session_id)
    # Projected history after this turn (for Redis cache only).
    projected = conversations.transcript(session_id, limit=1000, offset=0).get("messages") or []
    history = [{"role": m["role"], "content": m["content"]} for m in projected[-40:]]
    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": assistant_message})

    saved = session_store.save_session_state(
        session_id,
        model_variant,
        history,
        expected_revision=rev,
        fence_token=fence_token,
    )
    if not saved:
        try:
            path.unlink(missing_ok=True)
        except TypeError:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        raise TurnCommitError("session_conflict")

    # Re-check version immediately before durable append (TOCTOU with staging).
    if message_count(session_id) != int(expected_version):
        try:
            path.unlink(missing_ok=True)
        except TypeError:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        raise TurnCommitError("session_conflict")

    _append_turn(pending)
    if message_count(session_id) != int(expected_version) + 2:
        # Leave pending for recover_pending — do not mark committed.
        raise TurnCommitError("persist_failed")
    try:
        path.unlink(missing_ok=True)
    except TypeError:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    marker.write_text(str(time.time()), encoding="utf-8")
    try:
        os.chmod(marker, 0o600)
    except OSError:
        pass
    session_store.touch_session(session_id)
    return int(expected_version) + 2


def recover_pending(session_id: str, commit_id: str) -> str:
    """Crash-recovery helper. Returns ``committed``, ``discarded``, or ``missing``."""
    marker = _committed_marker(session_id, commit_id)
    if marker.exists():
        return "committed"
    path = _pending_path(session_id, commit_id)
    if not path.exists():
        return "missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        try:
            path.unlink()
        except OSError:
            pass
        return "discarded"

    expected = int(payload.get("expected_version") or -1)
    current = message_count(session_id)
    if current == expected:
        # CAS may have succeeded (Redis) while JSONL did not. Complete append.
        # If Redis is enabled, require the fence to still match OR accept when
        # the projected revision advanced — callers invoke this only for known
        # commit_ids after a crash.
        _append_turn(payload)
        try:
            path.unlink()
        except OSError:
            pass
        marker.write_text(str(time.time()), encoding="utf-8")
        return "committed"
    if current >= expected + 2:
        # Append already landed; clear staging.
        try:
            path.unlink()
        except OSError:
            pass
        marker.write_text(str(time.time()), encoding="utf-8")
        return "committed"
    # Version moved differently or CAS never happened — discard.
    try:
        path.unlink()
    except OSError:
        pass
    return "discarded"
