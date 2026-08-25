"""
Consent tracking, data-export requests, and a structured security-breach
log — adapted from a real, working pattern in a separate project, filling
a genuine gap Orca had none of before this: there was no structured record
of what a user had actually consented to, no way for a user to request
their data back (GDPR Art.20 / portability), and no dedicated table for
tracking security incidents.

Deliberately NOT duplicated here: account deletion. orca/serve/account_delete.py
already implements a real, working right-to-erasure flow (immediate,
password-gated, cross-store cleanup) — a "pending deletion request" queue
sitting on top of that would just be a redundant log entry for something
that's already instant and self-service, not a genuine gap.

Row-level security (Postgres only, see orca/auth/db.py's _RLS_POSTGRES) is
schema-level defense-in-depth, not yet wired into every call site here —
set_user_context()/set_service_context() below exist so a future pass can
adopt it incrementally; every function in this module still works
correctly without it today because it filters by user_id explicitly in
its own SQL, same as the rest of orca/auth/store.py.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from orca.auth.db import get_conn, BACKEND

# Must match the CHECK constraint the frontend/API validates against —
# kept as a plain Python set (not a DB CHECK constraint on SQLite, which
# doesn't enforce CHECK on ALTER-added columns the same way Postgres does)
# so both backends reject the same invalid values at the application layer.
CONSENT_PURPOSES = frozenset({
    "analytics",
    "marketing_email",
    "personalization",
    "data_sharing",
    "training",
    "third_party",
    "cookies_necessary",
    "cookies_analytics",
    "cookies_marketing",
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def set_user_context(conn, user_id: str) -> None:
    """Postgres-only — no-op on SQLite (single-process, RLS doesn't apply)."""
    if BACKEND == "postgres":
        conn.execute("SELECT orca_security.set_user_context(?)", (user_id,))


def set_service_context(conn) -> None:
    """Postgres-only — no-op on SQLite."""
    if BACKEND == "postgres":
        conn.execute("SELECT orca_security.set_service_context()")


# ─────────────────────────────────────────────────────────────────────────────
#  Consent tracking
# ─────────────────────────────────────────────────────────────────────────────

def set_consent(
    user_id: str,
    purpose: str,
    granted: bool,
    legal_basis: str = "consent",
    version: str = "1.0",
    source: str = "web",
) -> dict:
    """
    Records a user's consent decision for one purpose. Idempotent per
    (user_id, purpose) — a second call updates the existing row rather than
    creating a duplicate, and every change (including the very first grant)
    is mirrored into consent_audit_log, which is append-only (enforced by
    trigger/rule at the DB layer, not just application convention — see
    orca/auth/db.py).
    """
    if purpose not in CONSENT_PURPOSES:
        raise ValueError(f"Unknown consent purpose: {purpose!r}")

    now = _now()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT granted FROM privacy_consents WHERE user_id = ? AND purpose = ?",
            (user_id, purpose),
        ).fetchone()
        previous_state = bool(row["granted"]) if row else None

        if row is None:
            conn.execute(
                """INSERT INTO privacy_consents
                   (id, user_id, purpose, granted, legal_basis, version, source,
                    granted_at, revoked_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()), user_id, purpose, int(granted), legal_basis,
                    version, source, now if granted else None, None if granted else now, now,
                ),
            )
        else:
            conn.execute(
                """UPDATE privacy_consents
                   SET granted = ?, legal_basis = ?, version = ?, source = ?,
                       granted_at = CASE WHEN ? THEN ? ELSE granted_at END,
                       revoked_at = CASE WHEN ? THEN NULL ELSE ? END,
                       updated_at = ?
                   WHERE user_id = ? AND purpose = ?""",
                (
                    int(granted), legal_basis, version, source,
                    int(granted), now,
                    int(granted), now,
                    now, user_id, purpose,
                ),
            )

        action = "granted" if granted else "revoked"
        if previous_state is not None and previous_state == granted:
            action = "updated"
        conn.execute(
            """INSERT INTO consent_audit_log
               (id, user_id, purpose, action, previous_state, new_state, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()), user_id, purpose, action,
                None if previous_state is None else int(previous_state),
                int(granted), now,
            ),
        )

    return {"user_id": user_id, "purpose": purpose, "granted": granted, "updated_at": now}


def get_consents(user_id: str) -> dict[str, dict]:
    """Returns every recorded consent for a user, keyed by purpose."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT purpose, granted, legal_basis, version, source, granted_at,
                      revoked_at, updated_at
               FROM privacy_consents WHERE user_id = ?""",
            (user_id,),
        ).fetchall()
    return {
        r["purpose"]: {
            "granted": bool(r["granted"]),
            "legal_basis": r["legal_basis"],
            "version": r["version"],
            "source": r["source"],
            "granted_at": r["granted_at"],
            "revoked_at": r["revoked_at"],
            "updated_at": r["updated_at"],
        }
        for r in rows
    }


def get_consent_audit_trail(user_id: str) -> list[dict]:
    """Full history of consent changes for a user — the actual evidence of
    consent a legal request would need, not just the current state."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT purpose, action, previous_state, new_state, created_at
               FROM consent_audit_log WHERE user_id = ? ORDER BY created_at ASC""",
            (user_id,),
        ).fetchall()
    return [
        {
            "purpose": r["purpose"],
            "action": r["action"],
            "previous_state": None if r["previous_state"] is None else bool(r["previous_state"]),
            "new_state": bool(r["new_state"]),
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def init_default_consents(user_id: str) -> None:
    """Call once at signup — seeds the one consent that isn't really
    optional (strictly necessary cookies) so get_consents() has a real row
    to show from day one instead of implying nothing was ever decided."""
    set_consent(user_id, "cookies_necessary", granted=True, legal_basis="legitimate_interest", source="default")


# ─────────────────────────────────────────────────────────────────────────────
#  Data export requests (GDPR Art.20 / data portability)
# ─────────────────────────────────────────────────────────────────────────────

def request_data_export(user_id: str) -> dict:
    """
    Records a pending export request. Deliberately does NOT generate the
    export file itself — that's a separate worker's job (gathering account
    row, sessions, consents, audit trail into one archive), out of scope
    for this module. This function's honest job is just the request
    record: one pending request per user at a time, enforced here rather
    than at the DB layer since SQLite's partial-unique-index syntax differs
    from Postgres's and duplicating that dialect split isn't worth it for
    one check.
    """
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM data_export_requests WHERE user_id = ? AND status IN ('pending', 'processing')",
            (user_id,),
        ).fetchone()
        if existing:
            raise ValueError("An export request is already pending for this user.")

        req_id = str(uuid.uuid4())
        now = _now()
        conn.execute(
            """INSERT INTO data_export_requests (id, user_id, status, requested_at)
               VALUES (?, ?, 'pending', ?)""",
            (req_id, user_id, now),
        )
    return {"id": req_id, "user_id": user_id, "status": "pending", "requested_at": now}


def mark_export_complete(request_id: str, file_path: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE data_export_requests SET status = 'completed', completed_at = ?, file_path = ? WHERE id = ?",
            (_now(), file_path, request_id),
        )


def mark_export_failed(request_id: str, error_message: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE data_export_requests SET status = 'failed', error_message = ? WHERE id = ?",
            (error_message, request_id),
        )


def get_export_requests(user_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, status, requested_at, completed_at, file_path, error_message
               FROM data_export_requests WHERE user_id = ? ORDER BY requested_at DESC""",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
#  Security breach log
# ─────────────────────────────────────────────────────────────────────────────

BREACH_TYPES = frozenset({
    "unauthorized_access", "data_leak", "credential_compromise",
    "phishing", "insider_threat", "third_party", "accidental", "other",
})


def log_breach(
    title: str,
    description: str,
    breach_type: str,
    discovered_at: str | None = None,
    severity: str = "medium",
    affected_user_ids: list[str] | None = None,
    data_categories: list[str] | None = None,
    reported_by: str = "unknown",
) -> dict:
    """
    Creates a new incident record. Immutable once created (DELETE is
    blocked at the DB layer — see security_breach_log's rule/trigger in
    orca/auth/db.py) — the historical fact that an incident was opened
    must survive even as its status/remediation fields get updated while
    it's being worked.
    """
    if breach_type not in BREACH_TYPES:
        raise ValueError(f"Unknown breach_type: {breach_type!r}")

    now = _now()
    breach_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO security_breach_log
               (id, title, severity, breach_type, affected_user_ids, affected_count,
                data_categories, description, discovered_at, status, reported_by,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)""",
            (
                breach_id, title, severity, breach_type,
                json.dumps(affected_user_ids or []),
                len(affected_user_ids) if affected_user_ids else None,
                json.dumps(data_categories or []),
                description, discovered_at or now, reported_by, now, now,
            ),
        )
    return {"id": breach_id, "title": title, "status": "open", "created_at": now}


def update_breach_status(breach_id: str, status: str, remediation_steps: str | None = None) -> None:
    valid_statuses = {"open", "investigating", "contained", "resolved", "closed"}
    if status not in valid_statuses:
        raise ValueError(f"Unknown status: {status!r}")
    now = _now()
    with get_conn() as conn:
        if status == "contained":
            conn.execute(
                "UPDATE security_breach_log SET status = ?, contained_at = ?, remediation_steps = COALESCE(?, remediation_steps), updated_at = ? WHERE id = ?",
                (status, now, remediation_steps, now, breach_id),
            )
        else:
            conn.execute(
                "UPDATE security_breach_log SET status = ?, remediation_steps = COALESCE(?, remediation_steps), updated_at = ? WHERE id = ?",
                (status, remediation_steps, now, breach_id),
            )


def mark_users_notified(breach_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE security_breach_log SET users_notified = 1, users_notified_at = ? WHERE id = ?",
            (_now(), breach_id),
        )


def list_breaches(status: str | None = None) -> list[dict]:
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM security_breach_log WHERE status = ? ORDER BY discovered_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM security_breach_log ORDER BY discovered_at DESC"
            ).fetchall()

    results = []
    for r in rows:
        d = dict(r)
        d["affected_user_ids"] = json.loads(d["affected_user_ids"] or "[]")
        d["data_categories"] = json.loads(d["data_categories"] or "[]")
        results.append(d)
    return results
