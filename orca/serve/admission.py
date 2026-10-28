"""Unified serving-admission boundary for chat, stream, and inference routes.

Every billable model dispatch must pass through ``admit_serving`` before a
provider is contacted. Security decisions (identity, ownership, entitlement,
moderation, atomic quota) live here once — route adapters only translate
response shapes.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Optional

from orca.auth.store import (
    QuotaError,
    User,
    mark_quota_consumed,
    model_access_allowed,
    release_quota,
    reservation_fingerprint,
    reserve_quota,
)
from orca.serve.errors import coded_error
from orca.serve.moderation import check_input
from orca.serve import metrics
from orca import audit


@dataclass(frozen=True)
class Admission:
    """Outcome of serving admission. ``ok`` means a fresh reservation was taken."""

    ok: bool
    user: Optional[User]
    session_id: str
    request_id: str
    fingerprint: str
    model: str
    quota_kind: str
    reservation: dict
    refusal: Any = None  # PublicError-compatible or None
    replay: dict | None = None


def require_valid_credentials(user: Optional[User], *, allow_anonymous: bool) -> Any:
    """Return a coded error when anonymous access is not permitted.

    Invalid/expired/revoked credentials must already have been rejected by the
    auth dependency before this is called. This only enforces the route's
    anonymous-access policy for *missing* credentials.
    """
    if user is None and not allow_anonymous:
        return coded_error("auth_required", message="Authentication required")
    return None


def enforce_session_ownership(session_id: str | None, user: Optional[User]) -> Any:
    """Refuse when a session id is present but the caller does not own it.

    Always ``not_found`` (404): do not reveal whether the session exists.
    """
    if not session_id:
        return None
    if user is None:
        return coded_error("not_found", message="Session not found")
    try:
        from orca.auth.store import check_session_access

        if not check_session_access(session_id, user.id):
            return coded_error("not_found", message="Session not found")
    except Exception:
        return coded_error("not_found", message="Session not found")
    return None


def admit_serving(
    *,
    user: Optional[User],
    message: str,
    model: str,
    session_id: str = "",
    route: str,
    quota_kind: str = "message",
    request_id: str | None = None,
    allow_anonymous: bool = False,
    require_ownership: bool = True,
) -> Admission:
    """Single admission gate shared by /api/chat, /api/stream, /api/inference/*.

    Order:
      1. Anonymous policy (missing credentials only)
      2. Session ownership (when a session id is supplied)
      3. Model entitlement
      4. Input moderation
      5. Atomic quota reservation (authenticated callers only)
    """
    sid = (session_id or "").strip()
    model_name = (model or "nano").strip() or "nano"
    rid = (request_id or "").strip() or uuid.uuid4().hex

    auth_err = require_valid_credentials(user, allow_anonymous=allow_anonymous)
    if auth_err is not None:
        return Admission(
            ok=False,
            user=user,
            session_id=sid,
            request_id=rid,
            fingerprint="",
            model=model_name,
            quota_kind=quota_kind,
            reservation={},
            refusal=auth_err,
        )

    if require_ownership and sid:
        own_err = enforce_session_ownership(sid, user)
        if own_err is not None:
            return Admission(
                ok=False,
                user=user,
                session_id=sid,
                request_id=rid,
                fingerprint="",
                model=model_name,
                quota_kind=quota_kind,
                reservation={},
                refusal=own_err,
            )

    model_allowed, model_reason = model_access_allowed(user, model_name)
    if not model_allowed:
        return Admission(
            ok=False,
            user=user,
            session_id=sid,
            request_id=rid,
            fingerprint="",
            model=model_name,
            quota_kind=quota_kind,
            reservation={},
            refusal=coded_error("model_access_denied", message=model_reason),
        )

    mod_result = check_input(message or "")
    metrics.record_moderation_action(mod_result.action)
    if mod_result.action == "block":
        audit.log(
            "input_moderation_blocked",
            user_id=user.id if user else None,
            detail={"categories": mod_result.flagged_categories, "endpoint": route},
        )
        return Admission(
            ok=False,
            user=user,
            session_id=sid,
            request_id=rid,
            fingerprint="",
            model=model_name,
            quota_kind=quota_kind,
            reservation={},
            refusal=coded_error("content_refused"),
        )
    if mod_result.action in ("support", "flag"):
        audit.log(
            f"input_moderation_{mod_result.action}",
            user_id=user.id if user else None,
            detail={"categories": mod_result.flagged_categories, "endpoint": route},
        )

    if user is None:
        # Anonymous routes that allow missing credentials still cannot reserve.
        return Admission(
            ok=True,
            user=None,
            session_id=sid,
            request_id=rid,
            fingerprint="",
            model=model_name,
            quota_kind=quota_kind,
            reservation={"ok": True, "status": "anonymous", "request_id": rid},
        )

    fp = reservation_fingerprint(
        user_id=user.id,
        kind=quota_kind,
        session_id=sid,
        model=model_name,
        message=message or "",
    )
    try:
        reservation = reserve_quota(
            user.id,
            user.tier,
            quota_kind,
            request_id=rid,
            fingerprint=fp,
        )
    except Exception as exc:
        # Catch by attribute: pytest fixtures may reload orca.auth.store so a
        # statically imported QuotaError class identity can miss the raise.
        code = getattr(exc, "code", None)
        if code is None and type(exc).__name__ != "QuotaError":
            raise
        code = code or str(exc) or "quota_unavailable"
        if code in {"reservation_forbidden", "reservation_mismatch"}:
            return Admission(
                ok=False,
                user=user,
                session_id=sid,
                request_id=rid,
                fingerprint=fp,
                model=model_name,
                quota_kind=quota_kind,
                reservation={},
                refusal=coded_error("quota_exceeded", message="Request could not be admitted"),
            )
        return Admission(
            ok=False,
            user=user,
            session_id=sid,
            request_id=rid,
            fingerprint=fp,
            model=model_name,
            quota_kind=quota_kind,
            reservation={},
            refusal=coded_error("quota_exceeded", message="Quota service unavailable"),
        )

    if reservation.get("ok"):
        return Admission(
            ok=True,
            user=user,
            session_id=sid,
            request_id=reservation["request_id"],
            fingerprint=fp,
            model=model_name,
            quota_kind=quota_kind,
            reservation=reservation,
        )

    status = reservation.get("status")
    if status == "consumed" and reservation.get("replay") is not None:
        return Admission(
            ok=False,
            user=user,
            session_id=sid,
            request_id=reservation["request_id"],
            fingerprint=fp,
            model=model_name,
            quota_kind=quota_kind,
            reservation=reservation,
            replay=dict(reservation["replay"]),
        )

    used = reservation.get("used")
    limit = reservation.get("limit")
    return Admission(
        ok=False,
        user=user,
        session_id=sid,
        request_id=reservation.get("request_id", rid),
        fingerprint=fp,
        model=model_name,
        quota_kind=quota_kind,
        reservation=reservation,
        refusal=coded_error(
            "quota_exceeded",
            message=f"Daily limit reached ({used}/{limit}). Upgrade to Pro for unlimited use.",
            used=used,
            limit=limit,
        ),
    )


def consume_admission(admission: Admission, response: dict | None = None) -> None:
    if not admission.user or not admission.request_id:
        return
    if admission.reservation.get("status") == "anonymous":
        return
    try:
        mark_quota_consumed(admission.request_id, response=response)
    except Exception as exc:
        if getattr(exc, "code", None) is None and type(exc).__name__ != "QuotaError":
            raise


def release_admission(admission: Admission) -> None:
    if not admission.user or not admission.request_id:
        return
    # Only refund an in-flight reservation; consumed/released/anonymous are terminal.
    if admission.reservation.get("status") != "reserved":
        return
    try:
        release_quota(admission.request_id)
    except Exception as exc:
        if getattr(exc, "code", None) is None and type(exc).__name__ != "QuotaError":
            raise
