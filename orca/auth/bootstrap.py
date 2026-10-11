"""G-021 -- founder-controlled, single-use owner bootstrap.

Before: the first account created on a fresh deployment silently became `owner` (a racy count-then-insert). On a new public deployment that was
"whoever signs up first runs the instance".

Now:
  * ordinary signup NEVER yields `owner` (see `store.create_user`);
  * the operator, with shell access to the host (the founder-controlled channel), issues a one-time token bound to ONE email:
        python -m orca.auth.bootstrap issue --email founder@example.com
  * the token is redeemed once, over the API, together with that email's password (`POST /api/auth/bootstrap-owner`);
  * completion is a database singleton (`owner_bootstrap`, PRIMARY KEY id=1): concurrent redemptions cannot both succeed;
  * an install that already has an owner keeps it (migration records it as `legacy_existing_owner`); no token can be redeemed over it;
  * a public edge (`ORNEUR_PUBLIC_EDGE`) with no owner refuses ordinary signup (fail closed) until bootstrap is complete.

Tokens: 256 random bits, only SHA-256 stored, default 1 h life (max 24 h), single use, email-bound. This module provisions no credential by itself.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import secrets
import sys
from datetime import datetime, timedelta, timezone

from orca.auth.db import get_conn
from orca.auth.store import User, _row_to_user, delete_account_rows, insert_user
from orca.auth.crypto import verify_password

DEFAULT_TTL_S = 3600
MAX_TTL_S = 86_400
_PREFIX = "orneur-owner-"


class BootstrapError(Exception):
    """`code` is stable and safe to return to the caller."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _norm(email: str) -> str:
    return email.lower().strip()


def owner_exists() -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM users WHERE role='owner'").fetchone()
    return bool(row and row["n"])


def public_edge() -> bool:
    from orca.config import orneur_env

    return orneur_env("PUBLIC_EDGE", "").strip().lower() in ("1", "true", "yes")


def signup_blocked_until_bootstrap() -> bool:
    """Fail closed: a public deployment with no owner is not open for ordinary signups."""
    return public_edge() and not owner_exists()


def issue_token(email: str, ttl_s: int = DEFAULT_TTL_S, replace_existing_unverified: bool = False) -> str:
    """Operator-only (CLI). Refuses when an owner already exists. Returns the plaintext token ONCE; only its hash is stored.

    ``replace_existing_unverified`` is the recovery path for a pre-registered ("squatted") account on the bound e-mail: when redeemed it deletes that account
    (only if it is NOT verified and NOT an owner) and creates the owner fresh. It is a property of the token row the operator created, never of the request."""
    if "@" not in email:
        raise BootstrapError("invalid_email")
    ttl_s = max(60, min(int(ttl_s), MAX_TTL_S))
    if owner_exists():
        raise BootstrapError("already_initialized")
    token = _PREFIX + secrets.token_urlsafe(32)
    now = _now()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO owner_bootstrap_tokens (token_hash, bound_email, issued_at, expires_at, replace_existing) VALUES (?,?,?,?,?)",
            (_hash(token), _norm(email), now.isoformat(), (now + timedelta(seconds=ttl_s)).isoformat(), 1 if replace_existing_unverified else 0),
        )
    return token


def revoke_outstanding() -> int:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM owner_bootstrap_tokens WHERE redeemed_at IS NULL")
        return cur.rowcount if cur.rowcount is not None else 0


def status() -> dict:
    with get_conn() as conn:
        done = conn.execute("SELECT method, completed_at FROM owner_bootstrap WHERE id=1").fetchone()
        pending = conn.execute(
            "SELECT COUNT(*) AS n FROM owner_bootstrap_tokens WHERE redeemed_at IS NULL AND expires_at > ?", (_now().isoformat(),)
        ).fetchone()
    return {
        "initialized": owner_exists(),
        "method": done["method"] if (done and owner_exists()) else None,
        "pending_tokens": pending["n"] if pending else 0,
    }


def redeem(token: str, email: str, password: str, name: str = "") -> User:
    """Atomic: token claim, account creation/promotion and the completion singleton commit together or not at all.

    Errors are uniform on purpose -- a wrong token, wrong email, expired or already-used token are all `invalid_token`, so the endpoint is not an oracle."""
    email_n = _norm(email)
    if not isinstance(token, str) or not token.startswith(_PREFIX) or len(token) > 200 or len(password) < 8 or "@" not in email_n:
        raise BootstrapError("invalid_token")
    th = _hash(token)
    now = _now().isoformat()
    from orca.auth.apikeys import _ensure_table as _ensure_api_keys_table
    _ensure_api_keys_table()                                          # DDL must not run inside the transaction below (SQLite write lock)
    with get_conn() as conn:
        if conn.execute("SELECT COUNT(*) AS n FROM users WHERE role='owner'").fetchone()["n"]:
            raise BootstrapError("already_initialized")
        row = conn.execute(
            "SELECT bound_email, expires_at, redeemed_at, replace_existing FROM owner_bootstrap_tokens WHERE token_hash=?", (th,)
        ).fetchone()
        if not row or row["redeemed_at"] or row["expires_at"] <= now or not hmac.compare_digest(row["bound_email"], email_n):
            raise BootstrapError("invalid_token")
        claimed = conn.execute(
            "UPDATE owner_bootstrap_tokens SET redeemed_at=?, redeemed_by=? WHERE token_hash=? AND redeemed_at IS NULL RETURNING token_hash",
            (now, email_n, th),
        ).fetchone()
        if not claimed:                       # lost the race for this token
            raise BootstrapError("invalid_token")

        existing_row = conn.execute("SELECT * FROM users WHERE email=?", (email_n,)).fetchone()
        if existing_row and row["replace_existing"] and existing_row["role"] != "owner" and not existing_row["verified"]:
            # Operator-authorised recovery from a pre-registered account. A VERIFIED account is never replaced: it falls through to the
            # password-proof promotion below.
            delete_account_rows(conn, existing_row["id"])           # inside this transaction: rolled back if completion is lost
            existing_row = None
        if existing_row:
            # An account for the bound email already exists (it signed up as a member): promote it, but only on proof of its password.
            if not verify_password(password, existing_row["password_hash"]):
                raise BootstrapError("invalid_token")
            conn.execute("UPDATE users SET role='owner' WHERE id=?", (existing_row["id"],))
            user = _row_to_user(existing_row)
            user.role = "owner"
        else:
            user = insert_user(conn, email_n, password, name, role="owner")

        # The singleton decides the race. A completion row whose owner no longer exists is void and replaced.
        conn.execute(
            "DELETE FROM owner_bootstrap WHERE id=1 AND owner_user_id NOT IN (SELECT id FROM users WHERE role='owner')"
        )
        won = conn.execute(
            "INSERT INTO owner_bootstrap (id, owner_user_id, completed_at, method) VALUES (1,?,?,'token') "
            "ON CONFLICT (id) DO NOTHING RETURNING id",
            (user.id, now),
        ).fetchone()
        if not won:
            raise BootstrapError("already_initialized")   # raising rolls back the token claim and the account
        conn.execute("DELETE FROM owner_bootstrap_tokens WHERE redeemed_at IS NULL")   # nothing else may be redeemed later
    return user


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m orca.auth.bootstrap", description="Founder-controlled owner bootstrap (G-021).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("issue", help="issue a single-use token bound to one email")
    i.add_argument("--email", required=True)
    i.add_argument("--ttl", type=int, default=DEFAULT_TTL_S, help=f"seconds (60..{MAX_TTL_S})")
    i.add_argument("--replace-unverified", action="store_true",
                   help="recovery: if an UNVERIFIED non-owner account already holds this e-mail, delete it and create the owner fresh")
    sub.add_parser("status")
    sub.add_parser("revoke", help="delete all unredeemed tokens")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "issue":
            token = issue_token(a.email, a.ttl, replace_existing_unverified=a.replace_unverified)
            note = " WARNING: redeeming this token will REPLACE an unverified account holding that e-mail." if a.replace_unverified else ""
            print(f"Bootstrap token for {_norm(a.email)} (shown once; single use; expires in {min(a.ttl, MAX_TTL_S)}s).{note}\n{token}")
        elif a.cmd == "status":
            print(status())
        else:
            print(f"revoked {revoke_outstanding()} token(s)")
    except BootstrapError as e:
        print(f"refused: {e.code}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(_main())
