"""Role-Based Access Control for Orneur enterprise tier."""
from __future__ import annotations

from fastapi import Depends, HTTPException

from orca.auth.middleware import get_current_user
from orca.auth.store import User

# Numeric rank — higher = more powerful
ROLE_RANK: dict[str, int] = {
    "owner":  40,
    "admin":  30,
    "member": 20,
    "viewer": 10,
}

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "owner":  {"admin", "manage_users", "audit_read", "chat", "ultra", "remember", "api_keys"},
    "admin":  {"manage_users", "audit_read", "chat", "ultra", "remember", "api_keys"},
    "member": {"chat", "ultra", "remember", "api_keys"},
    "viewer": {"chat"},
}


def has_permission(user: User, perm: str) -> bool:
    return perm in ROLE_PERMISSIONS.get(user.role, ROLE_PERMISSIONS["viewer"])


def require_permission(perm: str):
    """FastAPI dependency — 403 if user lacks the given permission."""
    async def _dep(user: User = Depends(get_current_user)) -> User:
        if not has_permission(user, perm):
            raise HTTPException(status_code=403, detail=f"Permission denied: requires '{perm}'")
        return user
    return _dep


def require_role(min_role: str):
    """FastAPI dependency — 403 if user's role rank is below min_role."""
    min_rank = ROLE_RANK.get(min_role, 0)

    async def _dep(user: User = Depends(get_current_user)) -> User:
        user_rank = ROLE_RANK.get(user.role, 0)
        if user_rank < min_rank:
            raise HTTPException(status_code=403, detail=f"Requires role: {min_role}")
        return user
    return _dep


def can_assign_role(actor_role: str, target_current_role: str, new_role: str) -> bool:
    """G-006: ``manage_users`` alone let an admin promote themselves (or a
    friend) to owner and demote the real owner. An actor may only change a
    user ranked strictly below themselves, and only to a rank strictly below
    their own; only an owner can create or change an owner/admin peer."""
    actor = ROLE_RANK.get(actor_role, 0)
    if actor >= ROLE_RANK["owner"]:
        return True
    return ROLE_RANK.get(target_current_role, 0) < actor and ROLE_RANK.get(new_role, 0) < actor
