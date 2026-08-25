"""
Enterprise/Team management — one organization per owning account.

Honest scope:
  - One org per user who invites someone (created lazily on first invite,
    not a separate "create org" step) — matches "Enterprise/Team" as an
    extension of an existing paid account, not a standalone multi-tenant
    product surface. Multi-org-per-user (someone belonging to several
    teams) is out of scope for this pass.
  - Seat limits are tied to the owner's own subscription tier (free/pro/
    enterprise), NOT a separate per-seat Stripe billing product. A real
    enterprise seat-billing integration (prorated seat add/remove billed
    through Stripe) is a genuinely separate, larger feature — this gives
    you real roster/role/invite management now, with an honest seat cap,
    not a fake unlimited system.
  - Invite delivery reuses the existing mailer (orca/license/mailer.py) if
    SMTP is configured; otherwise returns the invite link directly so the
    inviter can share it manually — same "graceful without SMTP" pattern
    already used for email verification elsewhere in this codebase.
"""
from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from orca.auth.db import get_conn

# Seat limits keyed by the ORG OWNER's tier — see module docstring for why
# this isn't a separate seat-billing product.
SEAT_LIMITS: dict[str, int] = {
    "free": 1,          # no team seats on the free tier — just the owner
    "pro": 5,
    "enterprise": 50,
}


@dataclass
class OrgMember:
    id: str
    org_id: str
    user_id: Optional[str]
    invited_email: str
    role: str
    status: str  # "invited" | "active"
    invited_at: str
    joined_at: Optional[str]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_or_create_org(owner_user_id: str, owner_name: str = "") -> str:
    """Returns the org id for this owner, creating one if none exists yet."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM organizations WHERE owner_user_id=?", (owner_user_id,)
        ).fetchone()
        if row:
            return row["id"]

        org_id = str(uuid.uuid4())
        name = f"{owner_name}'s Team" if owner_name else "My Team"
        conn.execute(
            "INSERT INTO organizations (id, name, owner_user_id, created_at) VALUES (?,?,?,?)",
            (org_id, name, owner_user_id, _now()),
        )
        return org_id


def get_seat_usage(org_id: str, owner_tier: str) -> dict:
    """Returns {used, limit} — used counts active members + pending invites (both consume a seat)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as n FROM org_members WHERE org_id=? AND status IN ('active','invited')",
            (org_id,),
        ).fetchone()
    used = row["n"] if row else 0
    limit = SEAT_LIMITS.get(owner_tier, SEAT_LIMITS["free"])
    return {"used": used + 1, "limit": limit}  # +1 for the owner, who isn't a row in org_members


def invite_member(org_id: str, owner_tier: str, email: str, role: str = "member") -> dict:
    """
    Adds a pending invite. Raises ValueError if the seat limit is already
    reached or the email is already a member/pending invite of this org —
    both are real, user-facing conditions, not internal errors.
    """
    email = email.lower().strip()
    if role not in ("member", "admin"):
        raise ValueError(f"Invalid role '{role}' — must be 'member' or 'admin'.")

    usage = get_seat_usage(org_id, owner_tier)
    if usage["used"] >= usage["limit"]:
        raise ValueError(
            f"Seat limit reached ({usage['used']}/{usage['limit']}). "
            f"Upgrade your plan to invite more team members."
        )

    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM org_members WHERE org_id=? AND invited_email=? AND status IN ('active','invited')",
            (org_id, email),
        ).fetchone()
        if existing:
            raise ValueError(f"{email} is already a member or has a pending invite.")

        member_id = str(uuid.uuid4())
        token = secrets.token_urlsafe(24)
        conn.execute(
            "INSERT INTO org_members (id, org_id, user_id, invited_email, role, status, invite_token, invited_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (member_id, org_id, None, email, role, "invited", token, _now()),
        )

    return {"member_id": member_id, "email": email, "role": role, "invite_token": token}


def accept_invite(token: str, user_id: str) -> dict:
    """
    Links an invited email to a real user_id once they've signed up/logged
    in and clicked the invite link. Does NOT check that user_id's account
    email matches invited_email — the invite link itself is the proof of
    access to that email, matching the same trust model as password-reset
    tokens elsewhere in this codebase.
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM org_members WHERE invite_token=? AND status='invited'", (token,)
        ).fetchone()
        if not row:
            raise ValueError("Invalid or already-used invite link.")

        conn.execute(
            "UPDATE org_members SET user_id=?, status='active', joined_at=?, invite_token=NULL WHERE id=?",
            (user_id, _now(), row["id"]),
        )
        return {"org_id": row["org_id"], "role": row["role"]}


def list_members(org_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT m.*, u.name as user_name FROM org_members m "
            "LEFT JOIN users u ON u.id = m.user_id "
            "WHERE m.org_id=? ORDER BY m.invited_at ASC",
            (org_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def set_member_role(org_id: str, member_id: str, role: str) -> None:
    if role not in ("member", "admin"):
        raise ValueError(f"Invalid role '{role}' — must be 'member' or 'admin'.")
    with get_conn() as conn:
        result = conn.execute(
            "UPDATE org_members SET role=? WHERE id=? AND org_id=?", (role, member_id, org_id)
        )
        if getattr(result, "rowcount", 1) == 0:
            raise ValueError("Member not found in this organization.")


def remove_member(org_id: str, member_id: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM org_members WHERE id=? AND org_id=?", (member_id, org_id))


def get_org_for_owner(owner_user_id: str) -> Optional[dict]:
    """Returns the org row for this owner, or None if they've never invited anyone."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM organizations WHERE owner_user_id=?", (owner_user_id,)
        ).fetchone()
    return dict(row) if row else None
