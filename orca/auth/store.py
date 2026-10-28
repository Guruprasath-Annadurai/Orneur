"""User CRUD and daily usage tracking."""
from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from orca.auth.db import BACKEND, get_conn
from orca.auth.crypto import hash_password, verify_password

DAILY_LIMITS: dict[str, dict[str, int]] = {
    "free":       {"messages": 50,  "ultra": 3},
    "pro":        {"messages": -1,  "ultra": 50},
    "enterprise": {"messages": -1,  "ultra": -1},
}


@dataclass
class User:
    id: str
    email: str
    name: str
    tier: str
    verified: bool
    role: str = "member"
    signup_seq: int | None = None
    # G-006: session tokens issued before this epoch-seconds instant are
    # rejected (bumped by update_password); 0.0 = never invalidated.
    tokens_valid_after: float = 0.0


# First-100 cohort gets Novus free regardless of tier — counted by global
# signup order (signup_seq), decided explicitly over "first 100 to try
# Novus" since that produces a different, harder-to-reason-about cohort.
NOVUS_FREE_SIGNUP_CUTOFF = 100

# Which paid tiers unlock a given model variant outright, independent of
# the early-cohort exception above.
_PAID_TIERS = {"pro", "enterprise"}


def model_access_allowed(user: "User | None", model_variant: str) -> tuple[bool, str]:
    """
    Gates genesis/novus/aeternum (nano/core/ultra) access by plan.

    Rules (decided explicitly, not inferred):
      - nano (Genesis): always free, no restriction, anonymous included.
      - core (Novus): free if tier is pro/enterprise, OR if the user is
        one of the first NOVUS_FREE_SIGNUP_CUTOFF global signups. Anonymous
        users (no account) do not get the early-cohort exception — there's
        no signup_seq to check without an account.
      - ultra (Aeternum): paid only (pro/enterprise), no free path, ever.

    Returns (allowed, reason) — reason is empty on success, else a message
    safe to show the user directly.
    """
    variant = (model_variant or "core").removeprefix("orca-")

    if variant == "nano":
        return True, ""

    if variant == "core":
        if user and user.tier in _PAID_TIERS:
            return True, ""
        if user and user.signup_seq is not None and user.signup_seq <= NOVUS_FREE_SIGNUP_CUTOFF:
            return True, ""
        return False, (
            "Novus is free for our first 100 users and a paid feature after that. "
            "Upgrade to Pro to unlock it, or sign in if you believe you qualify for early access."
        )

    if variant == "ultra":
        if user and user.tier in _PAID_TIERS:
            return True, ""
        return False, "Aeternum is a paid feature. Upgrade to Pro or Enterprise to unlock it."

    # Unknown variant — fail closed, don't silently allow an unrecognized model string through.
    return False, f"Unknown model variant: {model_variant!r}"


# ── User CRUD ─────────────────────────────────────────────────────────────────

def mark_verified(user_id: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE users SET verified=1 WHERE id=?", (user_id,))


def update_password(user_id: str, new_password: str) -> None:
    """Sets a new password AND invalidates every session token and reset
    link issued before this instant (G-006): a stolen token, or a reset
    link that was already used once, must not survive a password change."""
    import time

    from orca.auth.crypto import hash_password
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET password_hash=?, tokens_valid_after=? WHERE id=?",
            (hash_password(new_password), time.time(), user_id),
        )


def revoke_token(jti: str, user_id: str, expires_at: float) -> None:
    """Server-side revocation of ONE session token (logout). Idempotent."""
    with get_conn() as conn:
        conn.execute("INSERT INTO revoked_tokens (jti, user_id, expires_at) VALUES (?,?,?) ON CONFLICT DO NOTHING", (jti, user_id, float(expires_at)))


def is_token_revoked(jti: str) -> bool:
    with get_conn() as conn:
        return conn.execute("SELECT 1 AS x FROM revoked_tokens WHERE jti=?", (jti,)).fetchone() is not None


def purge_expired_revocations(now: float | None = None) -> int:
    """Deletes revocation rows whose token has expired anyway. Returns how many were removed."""
    import time as _t

    with get_conn() as conn:
        cur = conn.execute("DELETE FROM revoked_tokens WHERE expires_at < ?", (_t.time() if now is None else now,))
        return cur.rowcount or 0


def invalidate_all_sessions(user_id: str) -> None:
    """Sign the user out everywhere: every token issued before now is rejected (same epoch mechanism as a password change)."""
    import time as _t

    with get_conn() as conn:
        conn.execute("UPDATE users SET tokens_valid_after=? WHERE id=?", (_t.time(), user_id))


def _count_users() -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) as n FROM users").fetchone()
    return row["n"] if row else 0


def _claim_signup_seq(conn) -> int:
    """
    Atomically claims the next global signup sequence number. UPDATE...
    RETURNING is used (not a read-then-write count) so concurrent signups
    can't both land on the same number — Postgres row-locks the single
    counter row on UPDATE, SQLite serializes writes at the connection/file
    level; both make this race-safe under concurrent signups at scale.
    """
    row = conn.execute(
        "UPDATE signup_counter SET next_seq = next_seq + 1 WHERE id = 1 RETURNING next_seq"
    ).fetchone()
    # next_seq was already incremented — the value claimed by THIS signup
    # is one less than what's now stored (started at 1, so signup #1 claims 1).
    return row["next_seq"] - 1


def create_user(email: str, password: str, name: str = "") -> User:
    """Creates an ORDINARY (role `member`) account. G-021: signing up never
    confers `owner` -- not as the first account, not under any race. The owner
    is created only through `orca.auth.bootstrap` (operator-issued, single-use,
    email-bound token)."""
    with get_conn() as conn:
        return insert_user(conn, email, password, name, role="member")


def insert_user(conn, email: str, password: str, name: str = "", *, role: str = "member") -> User:
    uid = str(uuid.uuid4())
    ph  = hash_password(password)
    now = datetime.now(timezone.utc).isoformat()
    display = name or email.split("@")[0]
    seq = _claim_signup_seq(conn)
    conn.execute(
        "INSERT INTO users (id, email, name, password_hash, tier, role, created_at, signup_seq) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (uid, email.lower().strip(), display, ph, "free", role, now, seq),
    )
    return User(id=uid, email=email, name=display, tier="free", verified=False, role=role, signup_seq=seq)


def set_user_tier(user_id: str, tier: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE users SET tier=? WHERE id=?", (tier, user_id))


def set_stripe_customer_id(user_id: str, customer_id: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE users SET stripe_customer_id=? WHERE id=?", (customer_id, user_id))


def get_user_by_stripe_customer_id(customer_id: str) -> Optional[User]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE stripe_customer_id=?", (customer_id,)
        ).fetchone()
    return _row_to_user(row)


def get_stripe_customer_id(user_id: str) -> Optional[str]:
    """stripe_customer_id isn't on the User dataclass (billing-internal detail) — fetch directly."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT stripe_customer_id FROM users WHERE id=?", (user_id,)
        ).fetchone()
    return row["stripe_customer_id"] if row else None


# ── 2FA / TOTP ─────────────────────────────────────────────────────────────────

def set_pending_totp_secret(user_id: str, secret: str) -> None:
    """
    Stores a secret WITHOUT enabling 2FA — the user must prove they can
    generate a valid code (via enable_totp) before it takes effect. Prevents
    a half-finished setup from silently requiring 2FA on next login with no
    way for the user to have actually saved the secret in their app.
    """
    with get_conn() as conn:
        conn.execute("UPDATE users SET totp_secret=?, totp_enabled=0 WHERE id=?", (secret, user_id))


def enable_totp(user_id: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE users SET totp_enabled=1 WHERE id=?", (user_id,))


def disable_totp(user_id: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE users SET totp_secret=NULL, totp_enabled=0 WHERE id=?", (user_id,))


def get_totp_state(user_id: str) -> dict:
    """Returns {'secret': str|None, 'enabled': bool} — internal detail, not on the User dataclass."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT totp_secret, totp_enabled FROM users WHERE id=?", (user_id,)
        ).fetchone()
    if not row:
        return {"secret": None, "enabled": False}
    return {"secret": row["totp_secret"], "enabled": bool(row["totp_enabled"])}


def set_user_role(user_id: str, role: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))


def list_users(limit: int = 100, offset: int = 0) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, email, name, tier, role, created_at, verified "
            "FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return [dict(r) for r in rows]


def get_user_by_email(email: str) -> Optional[User]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email=?", (email.lower().strip(),)
        ).fetchone()
    return _row_to_user(row)


def get_user_by_id(uid: str) -> Optional[User]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return _row_to_user(row)


def authenticate(email: str, password: str) -> Optional[User]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email=?", (email.lower().strip(),)
        ).fetchone()
    if not row or not verify_password(password, row["password_hash"]):
        return None
    return _row_to_user(row)


def upgrade_tier(user_id: str, tier: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE users SET tier=? WHERE id=?", (tier, user_id))




def _row_to_user(row) -> Optional[User]:
    if not row:
        return None
    cols = row.keys() if hasattr(row, "keys") else []
    return User(
        id=row["id"],
        email=row["email"],
        name=row["name"],
        tier=row["tier"],
        verified=bool(row["verified"]),
        role=row["role"] if "role" in cols else "member",
        signup_seq=row["signup_seq"] if "signup_seq" in cols else None,
        tokens_valid_after=float(row["tokens_valid_after"] or 0) if "tokens_valid_after" in cols else 0.0,
    )


# ── Usage / quota ─────────────────────────────────────────────────────────────

def check_quota(user_id: str, tier: str, kind: str = "message") -> tuple[bool, int, int]:
    """Returns (allowed, used_today, daily_limit). -1 limit means unlimited."""
    today = date.today().isoformat()
    col   = "messages" if kind == "message" else "ultra_runs"
    limit = DAILY_LIMITS.get(tier, DAILY_LIMITS["free"]).get(
        "messages" if kind == "message" else "ultra", 50
    )
    with get_conn() as conn:
        row = conn.execute(
            f"SELECT {col} FROM usage_daily WHERE user_id=? AND date=?",
            (user_id, today),
        ).fetchone()
    used = row[col] if row else 0
    if limit == -1:
        return True, used, limit
    return used < limit, used, limit


RESERVATION_TTL_S = 120
TERMINAL_RETENTION_S = 86400
_QUOTA_UNAVAILABLE = "quota_unavailable"


class QuotaError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _quota_conn():
    if BACKEND == "postgres":
        return get_conn()
    from orca.auth.db import AUTH_DB

    AUTH_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(AUTH_DB), isolation_level="IMMEDIATE", check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ensure_reservations(conn) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS usage_reservations ("
        "request_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, kind TEXT NOT NULL, "
        "date TEXT NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_usage_reservations_status_created "
        "ON usage_reservations(status, created_at)"
    )


def _refund_stale_locked(conn, *, now: float) -> None:
    cutoff = now - RESERVATION_TTL_S
    rows = conn.execute(
        "SELECT request_id, user_id, kind, date FROM usage_reservations "
        "WHERE status='reserved' AND created_at < ?",
        (cutoff,),
    ).fetchall()
    for row in rows:
        claimed = conn.execute(
            "UPDATE usage_reservations SET status='released' WHERE request_id=? AND status='reserved'",
            (row["request_id"],),
        )
        if (claimed.rowcount or 0) != 1:
            continue
        col = "messages" if row["kind"] == "message" else "ultra_runs"
        conn.execute(
            f"UPDATE usage_daily SET {col}=CASE WHEN {col}>0 THEN {col}-1 ELSE 0 END "
            "WHERE user_id=? AND date=?",
            (row["user_id"], row["date"]),
        )
    conn.execute(
        "DELETE FROM usage_reservations WHERE status IN ('consumed','released') AND created_at < ?",
        (now - TERMINAL_RETENTION_S,),
    )


def reserve_quota(user_id: str, tier: str, kind: str = "message", request_id: str | None = None) -> dict:
    """Atomically admit one billable unit. Idempotent on request_id."""
    if not user_id:
        raise QuotaError("unauthenticated")
    rid = request_id or uuid.uuid4().hex
    if not isinstance(rid, str) or not rid.strip() or len(rid) > 128:
        raise QuotaError("invalid_request_id")
    today = date.today().isoformat()
    col = "messages" if kind == "message" else "ultra_runs"
    limit = DAILY_LIMITS.get(tier, DAILY_LIMITS["free"]).get("messages" if kind == "message" else "ultra", 50)
    now = time.time()
    try:
        conn = _quota_conn()
    except Exception as exc:
        raise QuotaError(_QUOTA_UNAVAILABLE) from exc
    try:
        with conn:
            _ensure_reservations(conn)
            _refund_stale_locked(conn, now=now)
            existing = conn.execute(
                "SELECT status FROM usage_reservations WHERE request_id=?",
                (rid,),
            ).fetchone()
            if existing:
                status = existing["status"]
                used_row = conn.execute(
                    f"SELECT {col} FROM usage_daily WHERE user_id=? AND date=?",
                    (user_id, today),
                ).fetchone()
                used = used_row[col] if used_row else 0
                if status == "released":
                    return {"ok": False, "request_id": rid, "used": used, "limit": limit, "status": status, "duplicate": True}
                return {"ok": True, "request_id": rid, "used": used, "limit": limit, "status": status, "duplicate": True}
            if BACKEND == "postgres":
                conn.execute(
                    "SELECT messages FROM usage_daily WHERE user_id=? AND date=? FOR UPDATE",
                    (user_id, today),
                )
            conn.execute(
                f"INSERT INTO usage_daily (user_id, date, {col}) VALUES (?,?,0) "
                "ON CONFLICT(user_id, date) DO NOTHING",
                (user_id, today),
            )
            if limit == -1:
                conn.execute(
                    f"UPDATE usage_daily SET {col}=usage_daily.{col}+1 WHERE user_id=? AND date=?",
                    (user_id, today),
                )
                admitted = True
            else:
                cur = conn.execute(
                    f"UPDATE usage_daily SET {col}=usage_daily.{col}+1 "
                    f"WHERE user_id=? AND date=? AND {col} < ?",
                    (user_id, today, limit),
                )
                admitted = (cur.rowcount or 0) == 1
            used_row = conn.execute(
                f"SELECT {col} FROM usage_daily WHERE user_id=? AND date=?",
                (user_id, today),
            ).fetchone()
            used = used_row[col] if used_row else 0
            if not admitted:
                conn.execute(
                    "INSERT INTO usage_reservations (request_id, user_id, kind, date, status, created_at) "
                    "VALUES (?,?,?,?, 'released', ?)",
                    (rid, user_id, kind, today, now),
                )
                return {"ok": False, "request_id": rid, "used": used, "limit": limit, "status": "released", "duplicate": False}
            conn.execute(
                "INSERT INTO usage_reservations (request_id, user_id, kind, date, status, created_at) "
                "VALUES (?,?,?,?, 'reserved', ?)",
                (rid, user_id, kind, today, now),
            )
            return {"ok": True, "request_id": rid, "used": used, "limit": limit, "status": "reserved", "duplicate": False}
    except QuotaError:
        raise
    except Exception as exc:
        raise QuotaError(_QUOTA_UNAVAILABLE) from exc
    finally:
        try:
            conn.close()
        except Exception:
            pass


def mark_quota_consumed(request_id: str) -> None:
    if not request_id:
        return
    try:
        conn = _quota_conn()
    except Exception as exc:
        raise QuotaError(_QUOTA_UNAVAILABLE) from exc
    try:
        with conn:
            _ensure_reservations(conn)
            conn.execute(
                "UPDATE usage_reservations SET status='consumed' WHERE request_id=? AND status='reserved'",
                (request_id,),
            )
    except QuotaError:
        raise
    except Exception as exc:
        raise QuotaError(_QUOTA_UNAVAILABLE) from exc
    finally:
        try:
            conn.close()
        except Exception:
            pass


def release_quota(request_id: str) -> None:
    """Refund a reservation that never consumed the model. Idempotent."""
    if not request_id:
        return
    try:
        conn = _quota_conn()
    except Exception as exc:
        raise QuotaError(_QUOTA_UNAVAILABLE) from exc
    try:
        with conn:
            _ensure_reservations(conn)
            row = conn.execute(
                "SELECT user_id, kind, date, status FROM usage_reservations WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if not row or row["status"] != "reserved":
                return
            claimed = conn.execute(
                "UPDATE usage_reservations SET status='released' WHERE request_id=? AND status='reserved'",
                (request_id,),
            )
            if (claimed.rowcount or 0) != 1:
                return
            col = "messages" if row["kind"] == "message" else "ultra_runs"
            conn.execute(
                f"UPDATE usage_daily SET {col}=CASE WHEN {col}>0 THEN {col}-1 ELSE 0 END "
                "WHERE user_id=? AND date=?",
                (row["user_id"], row["date"]),
            )
    except QuotaError:
        raise
    except Exception as exc:
        raise QuotaError(_QUOTA_UNAVAILABLE) from exc
    finally:
        try:
            conn.close()
        except Exception:
            pass


def increment_usage(user_id: str, kind: str = "message") -> None:
    today = date.today().isoformat()
    col   = "messages" if kind == "message" else "ultra_runs"
    with get_conn() as conn:
        conn.execute(
            f"INSERT INTO usage_daily (user_id, date, {col}) VALUES (?,?,1) "
            f"ON CONFLICT(user_id, date) DO UPDATE SET {col}=usage_daily.{col}+1",   # qualified: PostgreSQL rejects the bare column as ambiguous
            (user_id, today),
        )


def get_usage_history(user_id: str, days: int = 7) -> list[dict]:
    """Per-day counters for the last `days` days (newest first); days without activity are omitted."""
    days = max(1, min(int(days), 366))
    since = (date.today() - timedelta(days=days - 1)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT date, messages, ultra_runs FROM usage_daily WHERE user_id=? AND date>=? ORDER BY date DESC", (user_id, since)
        ).fetchall()
    return [{"date": r["date"], "messages": r["messages"], "ultra_runs": r["ultra_runs"]} for r in rows]


def get_user_sessions_with_created(user_id: str) -> list[tuple[str, str]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT session_id, created_at FROM user_sessions WHERE user_id=?", (user_id,)).fetchall()
    return [(r["session_id"], r["created_at"]) for r in rows]


def get_retention_days(user_id: str) -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT retention_days FROM user_settings WHERE user_id=?", (user_id,)).fetchone()
    return int(row["retention_days"]) if row else 0


def set_retention_days(user_id: str, days: int) -> None:
    if not (days == 0 or 1 <= days <= 3650):
        raise ValueError("retention_days must be 0 (keep) or 1..3650")
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO user_settings (user_id, retention_days, updated_at) VALUES (?,?,?) "
            "ON CONFLICT (user_id) DO UPDATE SET retention_days=excluded.retention_days, updated_at=excluded.updated_at",
            (user_id, int(days), now),
        )


def users_with_retention() -> list[tuple[str, int]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT user_id, retention_days FROM user_settings WHERE retention_days > 0").fetchall()
    return [(r["user_id"], int(r["retention_days"])) for r in rows]


def release_session(session_id: str, user_id: str) -> bool:
    """Removes the OWNER's claim on one session (and its storage-name claims) so the id and its names are free again. Only the owner's call succeeds."""
    with get_conn() as conn:
        row = conn.execute("SELECT user_id FROM user_sessions WHERE session_id=?", (session_id,)).fetchone()
        if not row or row["user_id"] != user_id:
            return False
        conn.execute("DELETE FROM session_storage_keys WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM user_sessions WHERE session_id=? AND user_id=?", (session_id, user_id))
    return True


def get_usage_today(user_id: str) -> dict:
    today = date.today().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM usage_daily WHERE user_id=? AND date=?", (user_id, today)
        ).fetchone()
    if not row:
        return {"messages": 0, "ultra_runs": 0}
    return {"messages": row["messages"], "ultra_runs": row["ultra_runs"]}


# ── User <-> session mapping (needed for account deletion to actually cascade) ──
# Chat history, uploaded documents, and memory files are keyed purely by
# session_id — nothing tied them to an owning user_id before this table
# existed, meaning "delete my account" had no way to find and remove them.

def record_user_session(user_id: str, session_id: str) -> None:
    """Records ``user_id`` as owner of ``session_id`` iff the session has no
    owner yet. First writer wins; a second user's attempt is silently a
    no-op here -- callers that must *refuse* the second user use
    ``claim_session()``, which reports the outcome."""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO user_sessions (user_id, session_id, created_at) VALUES (?,?,?) "
            "ON CONFLICT DO NOTHING",
            (user_id, session_id, datetime.now(timezone.utc).isoformat()),
        )


def _storage_keys(session_id: str) -> list[str]:
    """Every storage name a session id is reduced to, case-folded:
    long-term memory / semantic facts / keyword docs use ``session_id[:8]``
    (orca/brain/memory.py, orca/docs/store.py) and the document vector
    collection uses ``session_id[:12]`` with dashes removed. Two session ids
    that share ANY of these share that data, so each is claimed separately."""
    sid = session_id.lower()
    return [f"m:{sid[:8]}", f"d:{sid[:12].replace('-', '')}"]


def _prefix_owned_by_other_session(conn, session_id: str) -> bool:
    sid = session_id.lower()
    row = conn.execute(
        "SELECT 1 FROM user_sessions WHERE session_id <> ? AND "
        "(lower(substr(session_id, 1, 8)) = ? OR replace(lower(substr(session_id, 1, 12)), '-', '') = ?) LIMIT 1",
        (session_id, sid[:8], sid[:12].replace("-", "")),
    ).fetchone()
    return row is not None


def _prefix_claimed_by_other_session(conn, session_id: str) -> bool:
    for key in _storage_keys(session_id):
        claimed = conn.execute("SELECT session_id FROM session_storage_keys WHERE storage_key=?", (key,)).fetchone()
        if claimed and claimed["session_id"] != session_id:
            return True
    return False


def check_session_access(session_id: str, user_id: str | None) -> bool:
    """Read-only access decision. ``False`` means the caller must be told the
    session does not exist (404): another user owns it, an anonymous caller is
    naming an owned session, or ``session_id`` shares a storage name with a
    different session that is already claimed/owned."""
    with get_conn() as conn:
        if _prefix_claimed_by_other_session(conn, session_id) or _prefix_owned_by_other_session(conn, session_id):
            return False
        row = conn.execute("SELECT user_id FROM user_sessions WHERE session_id=?", (session_id,)).fetchone()
    return row is None or row["user_id"] == user_id


def claim_session(session_id: str, user_id: str | None) -> bool:
    """Atomically claim ``session_id`` (and its storage names) for ``user_id``.

    Check-then-record used to be two separate steps, so two workers could
    both see "unowned" and both record themselves as owner. Each INSERT here
    is conflict-resolved by the database (primary key on the storage name,
    unique index on ``user_sessions.session_id``) and the winner is then
    *read back*, so exactly one caller is told ``True``. An anonymous claim
    (``user_id`` None) reserves the storage names but leaves the session
    ownerless, as before.
    """
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        for key in _storage_keys(session_id):
            conn.execute(
                "INSERT INTO session_storage_keys (storage_key, session_id, created_at) VALUES (?,?,?) "
                "ON CONFLICT DO NOTHING",
                (key, session_id, now),
            )
        if _prefix_claimed_by_other_session(conn, session_id) or _prefix_owned_by_other_session(conn, session_id):
            return False
        if user_id:
            conn.execute(
                "INSERT INTO user_sessions (user_id, session_id, created_at) VALUES (?,?,?) ON CONFLICT DO NOTHING",
                (user_id, session_id, now),
            )
        row = conn.execute("SELECT user_id FROM user_sessions WHERE session_id=?", (session_id,)).fetchone()
    return row is None or row["user_id"] == user_id


def get_user_session_ids(user_id: str) -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT session_id FROM user_sessions WHERE user_id=?", (user_id,)
        ).fetchall()
    return [r["session_id"] for r in rows]


def get_session_owner(session_id: str) -> str | None:
    """The inverse of `record_user_session()` -- `None` means either the
    session was created anonymously (never recorded here) or doesn't
    exist; both are treated identically by callers (no owner to check
    against). A session WITH a recorded owner must only be readable by
    that same user_id -- see callers in orca/serve/api.py's
    knowledge/explain/session-export/session-load endpoints, none of
    which enforced this before (Phase 14C edge qualification finding:
    any caller who learned/guessed a session_id could read another
    user's full transcript regardless of their own identity)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT user_id FROM user_sessions WHERE session_id=?", (session_id,)
        ).fetchone()
    return row["user_id"] if row else None


def delete_user_account_records(user_id: str) -> None:
    """Deletes the account-level rows (users, usage_daily, api_keys, user_sessions).
    Does NOT touch session-scoped data (memory files, docs, Redis) — that's
    orchestrated separately in orca/serve/account_delete.py, since it needs
    access to DocStore/EpisodicMemory/session_store, which this module
    intentionally doesn't import (keeps store.py's dependency footprint to
    just the DB layer).

    api_keys' table is owned by orca/auth/apikeys.py, created lazily by that
    module's own _ensure_table() at import time — NOT by this module's
    schema. In the real app something else always imports apikeys.py first,
    so the table exists by the time anyone calls this function. But that's
    an import-order assumption, not a guarantee: a script, test, or future
    refactor that calls delete_user_account_records() without that import
    having happened yet would crash with "no such table: api_keys". Ensuring
    it here makes this function self-sufficient regardless of import order —
    CREATE TABLE IF NOT EXISTS is a no-op when the table already exists, so
    this changes nothing for the normal path."""
    from orca.auth.apikeys import _ensure_table as _ensure_api_keys_table
    _ensure_api_keys_table()

    with get_conn() as conn:
        delete_account_rows(conn, user_id)


def delete_account_rows(conn, user_id: str) -> None:
    """The account-level DELETEs on an existing connection, so a caller (owner bootstrap) can make them part of its own transaction.
    The ``api_keys`` table must already exist (see ``delete_user_account_records``)."""
    conn.execute("DELETE FROM api_keys WHERE user_id=?", (user_id,))
    conn.execute("DELETE FROM usage_daily WHERE user_id=?", (user_id,))
    conn.execute("DELETE FROM usage_reservations WHERE user_id=?", (user_id,))
    conn.execute("DELETE FROM user_settings WHERE user_id=?", (user_id,))
    conn.execute("DELETE FROM idempotency_keys WHERE user_id=?", (user_id,))
    conn.execute("DELETE FROM revoked_tokens WHERE user_id=?", (user_id,))
    conn.execute(
        "DELETE FROM session_storage_keys WHERE session_id IN "
        "(SELECT session_id FROM user_sessions WHERE user_id=?)",
        (user_id,),
    )
    conn.execute("DELETE FROM user_sessions WHERE user_id=?", (user_id,))
    conn.execute("DELETE FROM users WHERE id=?", (user_id,))
