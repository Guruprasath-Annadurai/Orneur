"""L02-04: account-security lifecycle primitives (verification, recovery, throttling).

* ``issue`` / ``consume`` - email-verification and password-reset tokens are SINGLE USE: the signed token carries a ``jti`` that exists as a row; consuming it is one atomic
  ``UPDATE ... WHERE used_at IS NULL AND expires_at > now AND email = <account's current email>``. A replay, an expired token, a token for a changed email, or a token
  superseded by a newer one all fail the same way. Issuing a token supersedes the user's earlier unused token of that purpose.
* ``may_send`` - per-ACCOUNT send ledger (minimum interval + daily cap) so the resend and forgot-password paths cannot be used to flood an inbox from many IPs.
* ``login_locked`` / ``record_login_failure`` / ``clear_login_failures`` - per-SUBJECT (email hash, whether or not the account exists) failure ledger, so a lockout never reveals
  which accounts exist, and credential stuffing is bounded per target, not only per source IP.
* ``verification_required`` - email verification gates use of the service ONLY when verified delivery is actually configured. With no delivery provider nobody could ever
  verify, so the gate is refused at configuration time (see ``orca.serve.config_validation``) instead of locking every user out.
"""
from __future__ import annotations

import hashlib
import time
import uuid

from orca.auth.db import get_conn

VERIFY_TTL_S = 24 * 3600
RESET_TTL_S = 3600
SEND_MIN_INTERVAL_S = 60.0
SEND_MAX_PER_DAY = 5
LOGIN_MAX_FAILURES = 8
LOGIN_WINDOW_S = 15 * 60


def _now() -> float:
    return time.time()


# ── one-time tokens ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

def issue(user_id: str, purpose: str, email: str, ttl_s: int) -> str:
    jti = uuid.uuid4().hex
    now = _now()
    with get_conn() as conn:
        conn.execute("UPDATE auth_one_time_tokens SET used_at=? WHERE user_id=? AND purpose=? AND used_at IS NULL", (now, user_id, purpose))   # supersede earlier links
        conn.execute("INSERT INTO auth_one_time_tokens (jti, user_id, purpose, email, expires_at, used_at, created_at) VALUES (?,?,?,?,?,NULL,?)",
                     (jti, user_id, purpose, email.lower().strip(), now + ttl_s, now))
        conn.execute("DELETE FROM auth_one_time_tokens WHERE expires_at < ?", (now - 7 * 86400,))
    return jti


def consume(jti: str | None, user_id: str, purpose: str, current_email: str) -> bool:
    """True exactly once per issued token, and only while it is unexpired and the account's email is still the one it was issued for."""
    if not jti:
        return False
    now = _now()
    with get_conn() as conn:
        cur = conn.execute("UPDATE auth_one_time_tokens SET used_at=? WHERE jti=? AND user_id=? AND purpose=? AND used_at IS NULL AND expires_at > ? AND email=?",
                           (now, jti, user_id, purpose, now, current_email.lower().strip()))
        return (cur.rowcount or 0) == 1


def peek(jti: str | None, user_id: str, purpose: str, current_email: str) -> bool:
    """Would ``consume`` succeed right now? (No state change - used to render a confirmation page without spending the link.)"""
    if not jti:
        return False
    with get_conn() as conn:
        row = conn.execute("SELECT 1 AS x FROM auth_one_time_tokens WHERE jti=? AND user_id=? AND purpose=? AND used_at IS NULL AND expires_at > ? AND email=?",
                           (jti, user_id, purpose, _now(), current_email.lower().strip())).fetchone()
    return row is not None


# ── send ledger ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def may_send(user_id: str, purpose: str) -> tuple[bool, float]:
    """(allowed, retry_after_seconds). Records the send when allowed."""
    now = _now()
    with get_conn() as conn:
        conn.execute("DELETE FROM auth_email_sends WHERE sent_at < ?", (now - 86400,))
        rows = conn.execute("SELECT sent_at FROM auth_email_sends WHERE user_id=? AND purpose=? ORDER BY sent_at DESC", (user_id, purpose)).fetchall()
        sent = [float(r["sent_at"]) for r in rows]
        if sent and now - sent[0] < SEND_MIN_INTERVAL_S:
            return False, SEND_MIN_INTERVAL_S - (now - sent[0])
        if len(sent) >= SEND_MAX_PER_DAY:
            return False, max(1.0, 86400 - (now - sent[-1]))
        conn.execute("INSERT INTO auth_email_sends (user_id, purpose, sent_at) VALUES (?,?,?)", (user_id, purpose, now))
    return True, 0.0


# ── login failures (per subject) ─────────────────────────────────────────────────────────────────────────────────────────────────

def _subject(email: str) -> str:
    return hashlib.sha256((email or "").lower().strip().encode()).hexdigest()


def login_locked(email: str) -> float:
    """Seconds until another attempt is allowed for this subject (0 = not locked). Identical for existing and non-existing accounts."""
    now = _now()
    with get_conn() as conn:
        rows = conn.execute("SELECT failed_at FROM auth_login_failures WHERE subject_hash=? AND failed_at > ? ORDER BY failed_at ASC", (_subject(email), now - LOGIN_WINDOW_S)).fetchall()
    if len(rows) < LOGIN_MAX_FAILURES:
        return 0.0
    return max(1.0, LOGIN_WINDOW_S - (now - float(rows[-LOGIN_MAX_FAILURES]["failed_at"])))


def record_login_failure(email: str) -> None:
    now = _now()
    with get_conn() as conn:
        conn.execute("DELETE FROM auth_login_failures WHERE failed_at < ?", (now - LOGIN_WINDOW_S,))
        conn.execute("INSERT INTO auth_login_failures (subject_hash, failed_at) VALUES (?,?)", (_subject(email), now))


def clear_login_failures(email: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM auth_login_failures WHERE subject_hash=?", (_subject(email),))


# ── step-up (L02-B3: fresh verification before a long-lived credential is minted) ───────────────────────────────────────────

def _stepup_subject(user_id: str) -> str:
    # prefixed so it can never equal a login subject (a bare 64-hex digest of an email address): a login attempt cannot lock a step-up
    return "stepup:" + hashlib.sha256((user_id or "").encode()).hexdigest()


def stepup_locked(user_id: str) -> float:
    now = _now()
    with get_conn() as conn:
        rows = conn.execute("SELECT failed_at FROM auth_login_failures WHERE subject_hash=? AND failed_at > ? ORDER BY failed_at ASC", (_stepup_subject(user_id), now - LOGIN_WINDOW_S)).fetchall()
    if len(rows) < LOGIN_MAX_FAILURES:
        return 0.0
    return max(1.0, LOGIN_WINDOW_S - (now - float(rows[-LOGIN_MAX_FAILURES]["failed_at"])))


def record_stepup_failure(user_id: str) -> None:
    now = _now()
    with get_conn() as conn:
        conn.execute("DELETE FROM auth_login_failures WHERE failed_at < ?", (now - LOGIN_WINDOW_S,))
        conn.execute("INSERT INTO auth_login_failures (subject_hash, failed_at) VALUES (?,?)", (_stepup_subject(user_id), now))


def clear_stepup_failures(user_id: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM auth_login_failures WHERE subject_hash=?", (_stepup_subject(user_id),))


def claim_totp_step(user_id: str, step: int) -> bool:
    """Atomically record that this authenticator time step was used for a step-up. False if it was already used (replay)."""
    now = _now()
    with get_conn() as conn:
        conn.execute("DELETE FROM auth_stepup_totp_used WHERE used_at < ?", (now - 600,))
        cur = conn.execute("INSERT INTO auth_stepup_totp_used (user_id, step, used_at) VALUES (?,?,?) ON CONFLICT (user_id, step) DO NOTHING", (user_id, int(step), now))
    return cur.rowcount == 1


# ── policy ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def verification_requested() -> bool:
    from orca.config import orneur_env

    return orneur_env("REQUIRE_EMAIL_VERIFICATION", "").strip().lower() in ("1", "true", "yes")


def verification_required() -> bool:
    """True only when the operator asked for it AND a delivery path exists. (A request without a delivery path is a configuration error caught at startup.)"""
    from orca.auth import email as mail

    return verification_requested() and mail.is_configured()
