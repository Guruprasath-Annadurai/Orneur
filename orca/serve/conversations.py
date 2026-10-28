"""Durable conversation history for signed-in users (Workstream B).

Consistency contract
--------------------
* **SQLite is the single source of truth** for committed turns
  (``conversation_turns``) and per-session fencing authority
  (``session_authority``). A Redis lease/revision claim is **advisory**
  coordination only and never authorizes an unconditional SQLite insert.
* **JSONL is a derived export** rebuilt from committed SQLite rows after a
  successful commit. It is never read as authoritative history.
* Legacy JSONL-only sessions are invisible until an explicit, durable
  ``reconcile_legacy_session`` migration marks the session verified.

Ownership is NEVER decided here: every caller must have passed the
session-ownership check first. File names are the full, validated session
id (``[A-Za-z0-9_-]{1,64}``).
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_MESSAGE_CHARS = 200_000
MAX_MESSAGES_PER_SESSION = 20_000
MAX_FILE_BYTES = 64 * 1024 * 1024
_SNIPPET_RADIUS = 70
DEFAULT_AUTHORITY_TTL_S = 45.0


def _dir() -> Path:
    # Prefer ``orca.brain.memory.MEMORY_DIR`` (tests monkeypatch it via the
    # client fixture). Fall back to config so fresh child processes that only
    # inherit ORCA_HOME/ORNEUR_HOME still resolve the same tree.
    import orca.brain.memory as mem
    import orca.config as config

    base = Path(getattr(mem, "MEMORY_DIR", None) or config.MEMORY_DIR)
    d = base / "conversations"
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def _path(session_id: str) -> Path:
    if not _SESSION_ID_RE.match(session_id or ""):
        raise ValueError("invalid session id")
    return _dir() / f"{session_id}.jsonl"


def _turns_db() -> Path:
    return _dir() / "turns.db"


def _turns_conn() -> sqlite3.Connection:
    path = _turns_db()
    conn = sqlite3.connect(str(path), isolation_level="IMMEDIATE", check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS conversation_turns ("
        "turn_id TEXT PRIMARY KEY,"
        "session_id TEXT NOT NULL,"
        "user_id TEXT NOT NULL,"
        "revision INTEGER NOT NULL,"
        "epoch INTEGER NOT NULL,"
        "fence_token TEXT NOT NULL,"
        "user_content TEXT NOT NULL,"
        "assistant_content TEXT NOT NULL,"
        "meta_json TEXT,"
        "created_at REAL NOT NULL,"
        "UNIQUE(session_id, revision)"
        ")"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_conversation_turns_session "
        "ON conversation_turns(session_id, revision)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS session_authority ("
        "session_id TEXT PRIMARY KEY,"
        "owner_user_id TEXT NOT NULL,"
        "fence_token TEXT NOT NULL,"
        "epoch INTEGER NOT NULL,"
        "expires_at REAL NOT NULL,"
        "committed_revision INTEGER NOT NULL DEFAULT 0,"
        "updated_at REAL NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS session_export_state ("
        "session_id TEXT PRIMARY KEY,"
        "export_revision INTEGER NOT NULL DEFAULT 0,"
        "export_pending INTEGER NOT NULL DEFAULT 0,"
        "migration_state TEXT NOT NULL DEFAULT 'unverified',"
        "updated_at REAL NOT NULL"
        ")"
    )
    # Additive migrations for pre-fencing turns tables.
    cols = {row[1] for row in conn.execute("PRAGMA table_info(conversation_turns)").fetchall()}
    if "epoch" not in cols:
        conn.execute("ALTER TABLE conversation_turns ADD COLUMN epoch INTEGER NOT NULL DEFAULT 0")
    if "fence_token" not in cols:
        conn.execute("ALTER TABLE conversation_turns ADD COLUMN fence_token TEXT NOT NULL DEFAULT ''")
    return conn


@dataclass(frozen=True)
class Authority:
    session_id: str
    user_id: str
    fence_token: str
    epoch: int
    committed_revision: int
    expires_at: float


@dataclass(frozen=True)
class CommitResult:
    ok: bool
    reason: str = ""
    turn_id: str = ""
    revision: int = 0
    epoch: int = 0


@dataclass(frozen=True)
class MigrationResult:
    ok: bool
    reason: str = ""
    imported_turns: int = 0
    state: str = "unverified"


def append(session_id: str, role: str, content: str, *, meta: dict | None = None, now: float | None = None) -> None:
    """Legacy single-message append — NOT an authoritative commit.

    Retained for callers that have not yet moved to ``commit_turn``. Writes
    only to the derived JSONL path and must not be used for inference
    transcript integrity. Prefer ``commit_turn`` under an acquired authority.
    """
    p = _path(session_id)
    if role not in ("user", "assistant", "system"):
        raise ValueError("invalid role")
    rec = {"role": role, "content": (content or "")[:MAX_MESSAGE_CHARS], "ts": float(time.time() if now is None else now)}
    if meta:
        rec["meta"] = meta
    line = (json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    try:
        if p.exists() and p.stat().st_size + len(line) > MAX_FILE_BYTES:
            return
        fd = os.open(p, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
    except OSError:
        return


def acquire_authority(
    session_id: str,
    user_id: str,
    fence_token: str,
    *,
    ttl_s: float = DEFAULT_AUTHORITY_TTL_S,
    now: float | None = None,
) -> Authority | None:
    """Acquire or renew durable session commit authority (short SQLite txn).

    A successor takeover increments ``epoch``, which invalidates any prior
    worker's commit rights. Does not stay open during model generation.
    """
    if not _SESSION_ID_RE.match(session_id or "") or not user_id or not fence_token:
        return None
    ts = float(time.time() if now is None else now)
    # Allow sub-second TTLs (tests / fast handoff). Production callers use ~45s.
    expires = ts + max(0.001, float(ttl_s))
    conn = _turns_conn()
    try:
        with conn:
            _ensure_export_row(conn, session_id, ts)
            row = conn.execute(
                "SELECT owner_user_id, fence_token, epoch, expires_at, committed_revision "
                "FROM session_authority WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO session_authority "
                    "(session_id, owner_user_id, fence_token, epoch, expires_at, committed_revision, updated_at) "
                    "VALUES (?,?,?,?,?,0,?)",
                    (session_id, user_id, fence_token, 1, expires, ts),
                )
                return Authority(session_id, user_id, fence_token, 1, 0, expires)
            if row["owner_user_id"] != user_id:
                return None
            same = row["fence_token"] == fence_token
            expired = float(row["expires_at"]) <= ts
            if same:
                conn.execute(
                    "UPDATE session_authority SET expires_at=?, updated_at=? WHERE session_id=? AND fence_token=?",
                    (expires, ts, session_id, fence_token),
                )
                return Authority(
                    session_id,
                    user_id,
                    fence_token,
                    int(row["epoch"]),
                    int(row["committed_revision"]),
                    expires,
                )
            if not expired:
                return None  # another live worker holds authority
            new_epoch = int(row["epoch"]) + 1
            conn.execute(
                "UPDATE session_authority SET fence_token=?, epoch=?, expires_at=?, updated_at=? "
                "WHERE session_id=? AND epoch=?",
                (fence_token, new_epoch, expires, ts, session_id, int(row["epoch"])),
            )
            # Confirm we won the epoch bump (concurrent takeover race).
            check = conn.execute(
                "SELECT fence_token, epoch, committed_revision, expires_at FROM session_authority WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if not check or check["fence_token"] != fence_token or int(check["epoch"]) != new_epoch:
                return None
            return Authority(
                session_id,
                user_id,
                fence_token,
                new_epoch,
                int(check["committed_revision"]),
                float(check["expires_at"]),
            )
    except Exception:
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def renew_authority(
    session_id: str,
    fence_token: str,
    epoch: int,
    *,
    ttl_s: float = DEFAULT_AUTHORITY_TTL_S,
    now: float | None = None,
) -> bool:
    """Extend authority expiry without changing epoch (short txn)."""
    if not _SESSION_ID_RE.match(session_id or "") or not fence_token or int(epoch) <= 0:
        return False
    ts = float(time.time() if now is None else now)
    expires = ts + max(0.001, float(ttl_s))
    conn = _turns_conn()
    try:
        with conn:
            cur = conn.execute(
                "UPDATE session_authority SET expires_at=?, updated_at=? "
                "WHERE session_id=? AND fence_token=? AND epoch=? AND expires_at > ?",
                (expires, ts, session_id, fence_token, int(epoch), ts),
            )
            return (cur.rowcount or 0) == 1
    except Exception:
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def release_authority(session_id: str, fence_token: str, epoch: int) -> bool:
    """Expire authority early so a successor can take over (crash-safe handoff)."""
    if not _SESSION_ID_RE.match(session_id or "") or not fence_token:
        return False
    ts = time.time()
    conn = _turns_conn()
    try:
        with conn:
            cur = conn.execute(
                "UPDATE session_authority SET expires_at=?, updated_at=? "
                "WHERE session_id=? AND fence_token=? AND epoch=?",
                (ts - 1.0, ts, session_id, fence_token, int(epoch)),
            )
            return (cur.rowcount or 0) == 1
    except Exception:
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def commit_turn(
    session_id: str,
    user_content: str,
    assistant_content: str,
    *,
    user_id: str,
    turn_id: str,
    fence_token: str,
    epoch: int,
    meta: dict | None = None,
    now: float | None = None,
    _test_crash_after_insert: bool = False,
    _test_skip_export: bool = False,
) -> CommitResult:
    """Commit one user/assistant turn under transactional SQLite fencing.

    Validates active authority (fence, epoch, expiry, ownership) and that the
    next revision is exactly ``committed_revision + 1`` inside the same
    transaction as the insert. JSONL is rebuilt only after COMMIT.
    """
    if not _SESSION_ID_RE.match(session_id or ""):
        raise ValueError("invalid session id")
    if not user_id or not turn_id or not fence_token or int(epoch) <= 0:
        return CommitResult(ok=False, reason="invalid_commit")
    ts = float(time.time() if now is None else now)
    conn = _turns_conn()
    new_revision = 0
    try:
        with conn:
            _ensure_export_row(conn, session_id, ts)
            # Idempotent retry of an already-committed turn_id.
            existing = conn.execute(
                "SELECT turn_id, revision, epoch, fence_token, user_id FROM conversation_turns WHERE turn_id=?",
                (turn_id,),
            ).fetchone()
            if existing:
                if (
                    existing["user_id"] == user_id
                    and int(existing["epoch"]) == int(epoch)
                    and existing["fence_token"] == fence_token
                ):
                    return CommitResult(
                        ok=True,
                        reason="idempotent",
                        turn_id=turn_id,
                        revision=int(existing["revision"]),
                        epoch=int(epoch),
                    )
                return CommitResult(ok=False, reason="duplicate_turn_id", turn_id=turn_id)

            auth = conn.execute(
                "SELECT owner_user_id, fence_token, epoch, expires_at, committed_revision "
                "FROM session_authority WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if auth is None:
                return CommitResult(ok=False, reason="authority_missing", turn_id=turn_id)
            if auth["owner_user_id"] != user_id:
                return CommitResult(ok=False, reason="ownership_mismatch", turn_id=turn_id)
            if auth["fence_token"] != fence_token or int(auth["epoch"]) != int(epoch):
                return CommitResult(ok=False, reason="stale_authority", turn_id=turn_id, epoch=int(epoch))
            if float(auth["expires_at"]) <= ts:
                return CommitResult(ok=False, reason="authority_expired", turn_id=turn_id, epoch=int(epoch))

            expected = int(auth["committed_revision"]) + 1
            # Reject out-of-order / superseded / duplicate revision.
            clash = conn.execute(
                "SELECT turn_id FROM conversation_turns WHERE session_id=? AND revision=?",
                (session_id, expected),
            ).fetchone()
            if clash:
                return CommitResult(ok=False, reason="revision_conflict", turn_id=turn_id, revision=expected)

            new_revision = expected
            conn.execute(
                "INSERT INTO conversation_turns "
                "(turn_id, session_id, user_id, revision, epoch, fence_token, "
                "user_content, assistant_content, meta_json, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    turn_id,
                    session_id,
                    user_id,
                    new_revision,
                    int(epoch),
                    fence_token,
                    (user_content or "")[:MAX_MESSAGE_CHARS],
                    (assistant_content or "")[:MAX_MESSAGE_CHARS],
                    json.dumps(meta or {}, default=str),
                    ts,
                ),
            )
            conn.execute(
                "UPDATE session_authority SET committed_revision=?, updated_at=? "
                "WHERE session_id=? AND fence_token=? AND epoch=? AND committed_revision=?",
                (new_revision, ts, session_id, fence_token, int(epoch), expected - 1),
            )
            bumped = conn.execute(
                "SELECT committed_revision FROM session_authority WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if not bumped or int(bumped["committed_revision"]) != new_revision:
                raise sqlite3.IntegrityError("committed_revision_cas_failed")
            conn.execute(
                "UPDATE session_export_state SET export_pending=1, updated_at=? WHERE session_id=?",
                (ts, session_id),
            )
            if _test_crash_after_insert:
                # Simulate process kill before COMMIT: roll back by raising.
                raise _TestCrash("crash_before_commit")
        # Transaction committed. Derived JSONL export is best-effort outside the txn;
        # export failure must not alter conversation truth or flip the commit result.
        if not _test_skip_export:
            try:
                _export_jsonl_from_sqlite(session_id)
            except Exception:
                pass
        return CommitResult(ok=True, turn_id=turn_id, revision=new_revision, epoch=int(epoch))
    except _TestCrash:
        return CommitResult(ok=False, reason="crash_before_commit", turn_id=turn_id, revision=new_revision, epoch=int(epoch))
    except Exception:
        return CommitResult(ok=False, reason="persist_failed", turn_id=turn_id, revision=new_revision, epoch=int(epoch))
    finally:
        try:
            conn.close()
        except Exception:
            pass


class _TestCrash(Exception):
    """Injected crash boundary for tests only."""


def _ensure_export_row(conn: sqlite3.Connection, session_id: str, ts: float) -> None:
    conn.execute(
        "INSERT INTO session_export_state (session_id, export_revision, export_pending, migration_state, updated_at) "
        "VALUES (?, 0, 0, 'unverified', ?) ON CONFLICT(session_id) DO NOTHING",
        (session_id, ts),
    )


def _messages_from_turns(turns: list[dict]) -> list[dict]:
    msgs: list[dict] = []
    for t in turns:
        meta = dict(t.get("meta") or {})
        meta.setdefault("turn_id", t["turn_id"])
        meta.setdefault("revision", t["revision"])
        msgs.append(
            {
                "role": "user",
                "content": t["user_content"],
                "ts": t.get("created_at"),
                "meta": {
                    "turn_id": t["turn_id"],
                    "revision": t["revision"],
                    **({"message_id": meta["user_message_id"]} if meta.get("user_message_id") else {}),
                },
            }
        )
        msgs.append(
            {
                "role": "assistant",
                "content": t["assistant_content"],
                "ts": t.get("created_at"),
                "meta": meta,
            }
        )
    return msgs


def turns_for_session(session_id: str) -> list[dict]:
    """Authoritative committed turns for a session (empty if none)."""
    if not _SESSION_ID_RE.match(session_id or ""):
        return []
    try:
        conn = _turns_conn()
    except Exception:
        raise
    try:
        rows = conn.execute(
            "SELECT turn_id, revision, epoch, fence_token, user_content, assistant_content, meta_json, created_at "
            "FROM conversation_turns WHERE session_id=? ORDER BY revision ASC",
            (session_id,),
        ).fetchall()
        out = []
        for row in rows:
            try:
                meta = json.loads(row["meta_json"] or "{}")
            except Exception:
                meta = {}
            out.append(
                {
                    "turn_id": row["turn_id"],
                    "revision": int(row["revision"]),
                    "epoch": int(row["epoch"] or 0),
                    "fence_token": row["fence_token"] or "",
                    "user_content": row["user_content"],
                    "assistant_content": row["assistant_content"],
                    "meta": meta,
                    "created_at": row["created_at"],
                }
            )
        return out
    finally:
        try:
            conn.close()
        except Exception:
            pass


def migration_state(session_id: str) -> str:
    if not _SESSION_ID_RE.match(session_id or ""):
        return "unverified"
    conn = _turns_conn()
    try:
        row = conn.execute(
            "SELECT migration_state FROM session_export_state WHERE session_id=?",
            (session_id,),
        ).fetchone()
        return str(row["migration_state"]) if row else "unverified"
    except Exception:
        return "unverified"
    finally:
        try:
            conn.close()
        except Exception:
            pass


def reconcile_legacy_session(session_id: str, user_id: str) -> MigrationResult:
    """Explicit, durable migration of legacy JSONL into SQLite SoT.

    Empty SQLite is never treated as permission to trust JSONL bytes until
    this function records ``migration_state='verified'``.
    """
    if not _SESSION_ID_RE.match(session_id or "") or not user_id:
        return MigrationResult(ok=False, reason="invalid_args")
    ts = time.time()
    fence = "migrate-" + uuid.uuid4().hex
    auth = acquire_authority(session_id, user_id, fence, ttl_s=30)
    if auth is None:
        return MigrationResult(ok=False, reason="authority_unavailable")
    conn = _turns_conn()
    imported = 0
    try:
        with conn:
            state_row = conn.execute(
                "SELECT migration_state FROM session_export_state WHERE session_id=?",
                (session_id,),
            ).fetchone()
            state = str(state_row["migration_state"]) if state_row else "unverified"
            existing = conn.execute(
                "SELECT COUNT(*) AS n FROM conversation_turns WHERE session_id=?",
                (session_id,),
            ).fetchone()["n"]
            if existing > 0 or state == "verified":
                conn.execute(
                    "UPDATE session_export_state SET migration_state='verified', updated_at=? WHERE session_id=?",
                    (ts, session_id),
                )
                return MigrationResult(ok=True, reason="already_verified", imported_turns=int(existing), state="verified")

            # Parse legacy JSONL into paired turns. Unpaired trailing user is dropped.
            raw_msgs = list(_iter_file(_path(session_id)))
            pairs: list[tuple[str, str, dict]] = []
            i = 0
            while i < len(raw_msgs):
                m = raw_msgs[i]
                if m["role"] == "user" and i + 1 < len(raw_msgs) and raw_msgs[i + 1]["role"] == "assistant":
                    ameta = raw_msgs[i + 1].get("meta") or {}
                    pairs.append((m["content"], raw_msgs[i + 1]["content"], ameta if isinstance(ameta, dict) else {}))
                    i += 2
                else:
                    i += 1

            rev = 0
            for user_c, asst_c, ameta in pairs:
                rev += 1
                tid = str(ameta.get("turn_id") or ("legacy-" + uuid.uuid4().hex))
                conn.execute(
                    "INSERT INTO conversation_turns "
                    "(turn_id, session_id, user_id, revision, epoch, fence_token, "
                    "user_content, assistant_content, meta_json, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        tid,
                        session_id,
                        user_id,
                        rev,
                        auth.epoch,
                        fence,
                        (user_c or "")[:MAX_MESSAGE_CHARS],
                        (asst_c or "")[:MAX_MESSAGE_CHARS],
                        json.dumps(ameta, default=str),
                        ts,
                    ),
                )
                imported += 1
            conn.execute(
                "UPDATE session_authority SET committed_revision=?, updated_at=? "
                "WHERE session_id=? AND fence_token=? AND epoch=?",
                (rev, ts, session_id, fence, auth.epoch),
            )
            conn.execute(
                "UPDATE session_export_state SET migration_state='verified', export_pending=1, "
                "export_revision=0, updated_at=? WHERE session_id=?",
                (ts, session_id),
            )
        _export_jsonl_from_sqlite(session_id)
        release_authority(session_id, fence, auth.epoch)
        return MigrationResult(ok=True, reason="migrated", imported_turns=imported, state="verified")
    except Exception:
        try:
            release_authority(session_id, fence, auth.epoch)
        except Exception:
            pass
        return MigrationResult(ok=False, reason="migration_failed", imported_turns=imported)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _export_jsonl_from_sqlite(session_id: str) -> bool:
    """Rebuild derived JSONL from committed turns via temp-file replace."""
    if not _SESSION_ID_RE.match(session_id or ""):
        return False
    try:
        turns = turns_for_session(session_id)
    except Exception:
        return False
    msgs = _messages_from_turns(turns)
    payload = b"".join(
        (json.dumps(m, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8") for m in msgs
    )
    if len(payload) > MAX_FILE_BYTES:
        return False
    p = _path(session_id)
    tmp = p.with_suffix(p.suffix + f".tmp.{uuid.uuid4().hex}")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            if payload:
                os.write(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, p)
        conn = _turns_conn()
        try:
            with conn:
                last_rev = turns[-1]["revision"] if turns else 0
                conn.execute(
                    "UPDATE session_export_state SET export_pending=0, export_revision=?, updated_at=? "
                    "WHERE session_id=?",
                    (int(last_rev), time.time(), session_id),
                )
        finally:
            conn.close()
        return True
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        return False


def reconcile_pending_exports() -> int:
    """Rebuild JSONL for sessions left with export_pending=1 after a crash."""
    conn = _turns_conn()
    try:
        rows = conn.execute(
            "SELECT session_id FROM session_export_state WHERE export_pending=1"
        ).fetchall()
    finally:
        conn.close()
    n = 0
    for row in rows:
        if _export_jsonl_from_sqlite(row["session_id"]):
            n += 1
    return n


def _iter_file(p: Path) -> Iterator[dict]:
    try:
        with open(p, "rb") as fh:
            for i, raw in enumerate(fh):
                if i >= MAX_MESSAGES_PER_SESSION:
                    return
                try:
                    rec = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(rec, dict) and rec.get("role") in ("user", "assistant", "system") and isinstance(rec.get("content"), str):
                    yield rec
    except FileNotFoundError:
        return


def _shown(session_id: str, rec: dict) -> tuple[str, dict]:
    """Active version text when one exists. The JSONL line is not rewritten."""
    meta = rec.get("meta") if isinstance(rec.get("meta"), dict) else {}
    message_id = meta.get("message_id")
    extra: dict = {}
    if isinstance(message_id, str):
        extra["message_id"] = message_id
        try:
            from orca.serve import message_versions

            view = message_versions.active_view(session_id, message_id)
        except Exception:
            view = None
        if view is not None:
            extra["version_id"] = view["version_id"]
            extra["version_count"] = view["version_count"]
            extra["edited"] = view["edited"]
            return view["content"], extra
    return rec["content"], extra


def find_message(session_id: str, message_id: str) -> dict | None:
    for rec in _iter_file(_path(session_id)):
        meta = rec.get("meta") if isinstance(rec.get("meta"), dict) else {}
        if meta.get("message_id") == message_id:
            return rec
    return None


def transcript(session_id: str, *, limit: int = 200, offset: int = 0) -> dict:
    """Read authoritative history from SQLite only.

    Never falls back to untrusted JSONL. Legacy JSONL is invisible until
    ``reconcile_legacy_session`` verifies migration state.
    """
    limit = max(1, min(int(limit), 1000))
    offset = max(0, int(offset))
    try:
        turns = turns_for_session(session_id)
    except Exception:
        # Fail closed: do not substitute JSONL.
        return {"session_id": session_id, "total": 0, "offset": offset, "limit": limit, "messages": [], "error": "sqlite_unavailable"}
    msgs = _messages_from_turns(turns)
    page = msgs[offset: offset + limit]
    rendered = []
    for i, message in enumerate(page):
        content, extra = _shown(session_id, message)
        row = {
            "index": offset + i,
            "role": message["role"],
            "content": content,
            "timestamp": message.get("ts"),
            **extra,
        }
        if message.get("meta"):
            row["meta"] = message["meta"]
        rendered.append(row)
    return {
        "session_id": session_id,
        "total": len(msgs),
        "offset": offset,
        "limit": limit,
        "messages": rendered,
    }


def last_activity(session_id: str) -> float | None:
    try:
        turns = turns_for_session(session_id)
        if turns:
            return float(turns[-1]["created_at"])
    except Exception:
        pass
    try:
        return _path(session_id).stat().st_mtime
    except (FileNotFoundError, ValueError):
        return None


def delete(session_id: str) -> bool:
    ok = False
    try:
        _path(session_id).unlink()
        ok = True
    except FileNotFoundError:
        ok = True
    except ValueError:
        return False
    try:
        conn = _turns_conn()
        try:
            with conn:
                conn.execute("DELETE FROM conversation_turns WHERE session_id=?", (session_id,))
                conn.execute("DELETE FROM session_authority WHERE session_id=?", (session_id,))
                conn.execute("DELETE FROM session_export_state WHERE session_id=?", (session_id,))
        finally:
            conn.close()
    except Exception:
        pass
    return ok


def _snippet(text: str, idx: int, qlen: int) -> str:
    a, b = max(0, idx - _SNIPPET_RADIUS), min(len(text), idx + qlen + _SNIPPET_RADIUS)
    s = text[a:b].replace("\n", " ")
    return ("…" if a else "") + s + ("…" if b < len(text) else "")


def search(session_ids: list[str], titles: dict[str, str], query: str, *, limit: int = 20, scan_cap: int = 500) -> dict:
    """Plain substring search over the caller's sessions using SQLite SoT."""
    q = query.casefold()
    scanned, results = 0, []
    for sid in session_ids[:scan_cap]:
        if not _SESSION_ID_RE.match(sid):
            continue
        scanned += 1
        title = titles.get(sid, "")
        matches, first = 0, None
        if q in title.casefold():
            matches += 1
            first = ("title", title, title.casefold().index(q))
        try:
            msgs = _messages_from_turns(turns_for_session(sid))
        except Exception:
            continue
        for m in msgs:
            c = m["content"].casefold()
            n = c.count(q)
            if n:
                matches += n
                if first is None:
                    first = (m["role"], m["content"], c.index(q))
        if matches:
            where, text, idx = first
            results.append(
                {
                    "session_id": sid,
                    "title": title,
                    "matches": matches,
                    "snippet": _snippet(text, idx, len(q)),
                    "in": where,
                    "updated_at": last_activity(sid),
                }
            )
    results.sort(key=lambda r: (r["updated_at"] or 0), reverse=True)
    return {
        "query": query,
        "results": results[:limit],
        "truncated": len(results) > limit or len(session_ids) > scan_cap,
        "scanned": scanned,
    }


def export_markdown(session_id: str, title: str) -> str:
    lines = [f"# {title}", f"\n_Exported from ORNEUR — {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}_\n", "---\n"]
    for m in transcript(session_id, limit=MAX_MESSAGES_PER_SESSION)["messages"]:
        who = {"user": "**You**", "assistant": "**ORNEUR**"}.get(m["role"], f"**{m['role']}**")
        lines.append(f"{who}\n\n{m['content']}\n")
        meta = m.get("meta") or {}
        ident = meta.get("model_identity") or {}
        if m["role"] == "assistant" and ident.get("served_model"):
            note = f"_Answered by {ident['served_model']}" + (
                f" (requested {ident.get('requested_tier')})" if ident.get("substituted") else ""
            ) + "_"
            lines.append(note + "\n")
        refs = meta.get("sources") or []
        if refs:
            lines.append(
                "Sources: "
                + "; ".join(f"[{s.get('ref')}] {s.get('filename') or s.get('url') or ''}" for s in refs)
                + "\n"
            )
        lines.append("---\n")
    return "\n".join(lines)


def export_json(session_id: str, title: str) -> dict:
    t = transcript(session_id, limit=MAX_MESSAGES_PER_SESSION)
    return {
        "schema": "orneur.conversation/1",
        "session_id": session_id,
        "title": title,
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total": t["total"],
        "messages": t["messages"],
    }
