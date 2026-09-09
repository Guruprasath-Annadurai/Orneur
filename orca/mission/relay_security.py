"""
Phase 15.12 / 15.12.1 -- Relay Security Modes: the server-side
capability-policy layer that makes `TRUSTED_DEVICE`/`PUBLIC_DEVICE`/
`MOBILE_REVIEW` technically different, not merely three strings on a
row.

Canonical distinctions this module exists to enforce (owner's own
closing lines, both phases):
  - Trusted does not mean ungoverned.
  - Public does not mean useless.
  - Mobile does not mean desktop shrunk onto a phone.
  - Reauthenticated does not mean authorized.
  - Raw secrets are never a Relay capability.
  - A real password check is not enough if the resulting proof can be
    forged.
  - A private-looking keyword is not a security boundary.
  - A session that already timed out must not become alive because
    heartbeat ran first.
  - The authoritative policy must load trust from durable state, not
    accept trust as an argument from the caller.

Architecture (spec section 0):

    AUTHENTICATED PRINCIPAL
            v
    DEVICE TRUST                <- LOADED FROM DURABLE STATE, never a caller argument
            v
    RELAY SESSION MODE          <- LOADED FROM DURABLE STATE, never a caller argument
            v
    SESSION VALIDITY            <- require_security_valid_session()
            v
    EFFECTIVE CAPABILITY POLICY <- effective_capabilities() (static, pure)
            v
    FRESH REAUTH CHECK where required  <- a real, server-issued ReauthGrant,
                                            looked up in a server-side store,
                                            never a caller-constructed object
            v
    EXISTING AUTHORITY ENGINE where required   <- orca.mission.operation_store /
                                                    orca.mission.authority_bridge,
                                                    NEVER touched or bypassed here
            v
    ACTION / SAFE STATE SURFACE

`RELAY POLICY PERMITS CAPABILITY` is never conflated with `AUTHORITY
ENGINE AUTHORIZES OPERATION` -- this module never calls into
`orca.mission.operation_store`/`orca.mission.authority_bridge`/
`orca.godmode.*` at all, in either direction.

15.12.1 CORRECTION (owner audit): the 15.12 version of this module let
an authoritative-looking `check_capability(..., reauth_valid=True)`
grant ALLOW directly from a caller-supplied boolean, and its
`ReauthContext` was a plain, publicly-constructible dataclass that
`is_reauth_context_valid()` validated purely from its OWN field
values -- meaning any caller could fabricate one
(`ReauthContext(user_id=me, expires_at=<far future>,
factors_verified=("password","totp"))`) without ever presenting a
real password or TOTP code, and it would pass. Both are fixed here:
- `check_capability()` is now a PURE, STATIC policy query only -- it
  answers "does this capability exist in this device-trust/mode
  combination, and would it need reauthentication/authority", and
  takes no `reauth_valid` parameter at all. It never claims a reauth-
  gated capability is CURRENTLY authorized.
- The new `authorize_relay_capability()` is the actual authoritative
  action gate: it loads the REAL `RelaySession`/`RelayDevice` from
  durable state (never trusting a caller-supplied `device_trust`/
  `mode`), and validates any required reauthentication against a REAL
  server-issued `ReauthGrant` -- an opaque handle whose only trustable
  content is a `secrets.token_urlsafe()` grant ID; the actual record
  (user, session, factors, expiry) lives server-side in
  `_REAUTH_GRANTS`, keyed by that ID. A caller who fabricates a
  `ReauthGrant` with a made-up ID gets a lookup miss -- fail closed.

No custom cryptography is added: password verification reuses
`orca.auth.crypto.verify_password` (PBKDF2-SHA256) via
`orca.auth.store.authenticate()`, TOTP verification reuses
`orca.auth.totp.verify_totp()` (RFC 6238) -- both already in the
codebase, already clock-injectable. The grant store's opaque IDs use
only `secrets.token_urlsafe()` (stdlib CSPRNG), not a bespoke scheme.

Grant store limitation, disclosed per spec section 15 (item 3): this
is an IN-PROCESS dict. A process restart invalidates every outstanding
grant -- fail closed (a grant that no longer exists cannot validate),
never fail open. No credential value (password, TOTP code/secret) is
ever stored in it.
"""
from __future__ import annotations

import re
import secrets as _secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from orca.mission.relay_store import (
    DeviceRevokedError,
    DeviceTrustLevel,
    RelayAccessDeniedError,
    RelayDevice,
    RelayError,
    RelayMode,
    RelaySession,
    RelaySessionNotFoundError,
    RelaySessionStatus,
    RelaySnapshot,
    build_relay_snapshot,
    get_device,
    get_session_for_user,
)
from orca.mission.relay_store import _insert_trusted_device_row
from orca.mission.relay_store import register_device as _register_device_primitive
from orca.mission.relay_store import revoke_all_other_sessions as _revoke_all_other_sessions_primitive
from orca.mission.relay_store import revoke_other_session as _revoke_other_session_primitive
from orca.mission.relay_store import revoke_session as _revoke_session_primitive
from orca.mission.relay_store import session_status as _session_status
from orca.mission.relay_store import touch_session as _touch_session_primitive


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ── Errors ────────────────────────────────────────────────────────────

class RelaySecurityError(RelayError):
    """Base class for Relay security-policy errors."""


class ReauthenticationError(RelaySecurityError):
    """Raised when fresh reauthentication genuinely fails (wrong
    password, wrong/missing TOTP, or no such account) -- never raised
    for a merely-expired/unknown PRIOR grant (see
    ReauthGrantInvalidError for that)."""


class ReauthGrantInvalidError(RelaySecurityError):
    """Raised when a `ReauthGrant` cannot be used for the requested
    action: unknown/fabricated grant ID, wrong user, wrong Relay
    session, or expired. A boolean or a client-fabricated dataclass is
    never accepted in its place -- validation always looks up the
    server-side grant store."""


class TrustedEnrollmentDeniedError(RelaySecurityError):
    """Raised when TRUSTED device enrollment is attempted without a
    valid, correctly-bound, server-issued ReauthGrant."""


class SessionSecurityInvalidError(RelaySecurityError):
    """Raised by `require_security_valid_session()` -- carries the
    specific `SecuritySessionStatus` reason."""

    def __init__(self, message: str, *, status: "SecuritySessionStatus"):
        super().__init__(message)
        self.status = status


# ── Capability vocabulary (spec section 1) ───────────────────────────

class RelayCapability(Enum):
    VIEW_MISSION_STATUS = "VIEW_MISSION_STATUS"
    VIEW_DIFF = "VIEW_DIFF"
    VIEW_TEST_RESULTS = "VIEW_TEST_RESULTS"
    VIEW_PRODUCTION_PROOF = "VIEW_PRODUCTION_PROOF"
    VIEW_BLOCKERS = "VIEW_BLOCKERS"

    MESSAGE_AGENT = "MESSAGE_AGENT"

    APPROVE = "APPROVE"
    REJECT = "REJECT"
    PAUSE_MISSION = "PAUSE_MISSION"
    RESUME_MISSION = "RESUME_MISSION"
    REVOKE_SESSION = "REVOKE_SESSION"

    VIEW_FILES = "VIEW_FILES"
    EDIT_FILES = "EDIT_FILES"
    OPEN_TERMINAL = "OPEN_TERMINAL"
    VIEW_LOGS = "VIEW_LOGS"
    RUN_TESTS = "RUN_TESTS"
    AGENT_CONTROL = "AGENT_CONTROL"

    DEPLOY_CONTROL = "DEPLOY_CONTROL"
    DANGEROUS_OPERATION_CONTROL = "DANGEROUS_OPERATION_CONTROL"

    DOWNLOAD_CONTENT = "DOWNLOAD_CONTENT"
    CLIPBOARD_EXPORT = "CLIPBOARD_EXPORT"


# Capabilities that are security-sensitive enough to require a REAL,
# validated reauthentication grant before `authorize_relay_capability()`
# will actually return ALLOW (spec section 13). This is a Relay-policy
# gate only -- it never substitutes for, and is always followed by,
# the real Authority Engine for the ones that also require it.
_REAUTH_REQUIRED_CAPABILITIES = frozenset({
    RelayCapability.DEPLOY_CONTROL,
    RelayCapability.DANGEROUS_OPERATION_CONTROL,
    RelayCapability.REVOKE_SESSION,
})

# Capabilities that, even when ALLOWED by Relay policy, must still
# pass through Phase 15.5's Authority Engine before any real side
# effect occurs (spec section 14: Relay policy != operation authority).
_AUTHORITY_REQUIRED_CAPABILITIES = frozenset({
    RelayCapability.DEPLOY_CONTROL,
    RelayCapability.DANGEROUS_OPERATION_CONTROL,
})

# ── Per-device-trust and per-mode capability surfaces (spec sections 3-5) ──
# Effective capability = INTERSECTION of both sets, never a union
# (spec section 2) -- see effective_capabilities() below.

_TRUSTED_DEVICE_CAPABILITIES: frozenset[RelayCapability] = frozenset(RelayCapability)  # everything is reachable AT THE DEVICE-TRUST layer; MODE further narrows it

_PUBLIC_DEVICE_CAPABILITIES: frozenset[RelayCapability] = frozenset({
    RelayCapability.VIEW_MISSION_STATUS,
    RelayCapability.VIEW_DIFF,
    RelayCapability.VIEW_TEST_RESULTS,
    RelayCapability.VIEW_PRODUCTION_PROOF,
    RelayCapability.VIEW_BLOCKERS,
    RelayCapability.MESSAGE_AGENT,
    RelayCapability.APPROVE,
    RelayCapability.REJECT,
    RelayCapability.PAUSE_MISSION,
    RelayCapability.RESUME_MISSION,
    RelayCapability.REVOKE_SESSION,
    RelayCapability.VIEW_LOGS,
    # Deliberately EXCLUDED (device-trust-level restriction, spec section 4):
    # EDIT_FILES, OPEN_TERMINAL, RUN_TESTS, AGENT_CONTROL, VIEW_FILES,
    # DEPLOY_CONTROL, DANGEROUS_OPERATION_CONTROL, DOWNLOAD_CONTENT,
    # CLIPBOARD_EXPORT -- this is what makes Public materially, testably
    # more restrictive than Trusted (closes REQ-DEVICE-REVOCATION-001's
    # second acceptance criterion).
})

_DEVICE_TRUST_CAPABILITIES: dict[DeviceTrustLevel, frozenset[RelayCapability]] = {
    DeviceTrustLevel.TRUSTED: _TRUSTED_DEVICE_CAPABILITIES,
    DeviceTrustLevel.PUBLIC: _PUBLIC_DEVICE_CAPABILITIES,
}

_TRUSTED_DEVICE_MODE_CAPABILITIES: frozenset[RelayCapability] = frozenset(RelayCapability)

_PUBLIC_DEVICE_MODE_CAPABILITIES: frozenset[RelayCapability] = _PUBLIC_DEVICE_CAPABILITIES

_MOBILE_REVIEW_MODE_CAPABILITIES: frozenset[RelayCapability] = frozenset({
    RelayCapability.VIEW_MISSION_STATUS,
    RelayCapability.VIEW_DIFF,
    RelayCapability.VIEW_TEST_RESULTS,
    RelayCapability.VIEW_PRODUCTION_PROOF,
    RelayCapability.VIEW_BLOCKERS,
    RelayCapability.MESSAGE_AGENT,
    RelayCapability.APPROVE,
    RelayCapability.REJECT,
    RelayCapability.PAUSE_MISSION,
    RelayCapability.RESUME_MISSION,
    RelayCapability.REVOKE_SESSION,
    # Deliberately EXCLUDED (spec section 5/18): OPEN_TERMINAL,
    # EDIT_FILES, VIEW_FILES, VIEW_LOGS, RUN_TESTS, AGENT_CONTROL,
    # DEPLOY_CONTROL, DANGEROUS_OPERATION_CONTROL, DOWNLOAD_CONTENT,
    # CLIPBOARD_EXPORT -- Mobile Review is a deliberately reduced
    # review/control surface, not a shrunk desktop IDE.
})

_RELAY_MODE_CAPABILITIES: dict[RelayMode, frozenset[RelayCapability]] = {
    RelayMode.TRUSTED_DEVICE: _TRUSTED_DEVICE_MODE_CAPABILITIES,
    RelayMode.PUBLIC_DEVICE: _PUBLIC_DEVICE_MODE_CAPABILITIES,
    RelayMode.MOBILE_REVIEW: _MOBILE_REVIEW_MODE_CAPABILITIES,
}


def effective_capabilities(*, device_trust: DeviceTrustLevel, mode: RelayMode) -> frozenset[RelayCapability]:
    """INTERSECTION, never union (spec section 2) -- a less-trusted
    device can never gain capability by selecting a more permissive
    RelayMode string, and a genuinely Trusted device that deliberately
    chooses PUBLIC_DEVICE mode gets PUBLIC restrictions, not Trusted
    capabilities. Pure function -- callers decide where `device_trust`/
    `mode` come from; see `authorize_relay_capability()` for the
    authoritative action gate, which loads both from durable state."""
    return _DEVICE_TRUST_CAPABILITIES[device_trust] & _RELAY_MODE_CAPABILITIES[mode]


@dataclass(frozen=True)
class PolicyDecision:
    capability: RelayCapability
    allowed: bool
    reason: str
    effective_mode: RelayMode
    device_trust: DeviceTrustLevel
    requires_reauthentication: bool
    requires_authority: bool
    requires_trusted_device_approval: bool


def check_capability(
    capability: RelayCapability | str, *, device_trust: DeviceTrustLevel, mode: RelayMode,
) -> PolicyDecision:
    """PURE, STATIC policy query (15.12.1 item 1/2) -- answers "is this
    capability within the effective policy set for this device-trust/
    mode combination, and would exercising it require reauthentication
    and/or the Authority Engine". It takes NO `reauth_valid` parameter
    and makes NO claim that a reauth-gated capability is CURRENTLY
    authorized -- `allowed=True` with `requires_reauthentication=True`
    means "policy-eligible, but a real, validated ReauthGrant is still
    required before this is actually authorized." The actual
    authoritative decision -- which also validates a real grant and
    loads `device_trust`/`mode` from durable session/device state
    rather than trusting the caller's arguments -- is
    `authorize_relay_capability()`.

    An unknown capability (anything not a real `RelayCapability`
    member, e.g. a string a model/provider might invent) always DENIES
    (spec section 1: 'Unknown capability => DENY'; spec section 9: 'No
    model/provider text may change security policy')."""
    if not isinstance(capability, RelayCapability):
        try:
            capability = RelayCapability(capability)
        except ValueError:
            return PolicyDecision(
                capability=capability, allowed=False, reason=f"unknown capability: {capability!r}",
                effective_mode=mode, device_trust=device_trust, requires_reauthentication=False,
                requires_authority=False, requires_trusted_device_approval=False,
            )

    effective = effective_capabilities(device_trust=device_trust, mode=mode)
    in_effective_set = capability in effective
    requires_reauth = capability in _REAUTH_REQUIRED_CAPABILITIES
    requires_authority = capability in _AUTHORITY_REQUIRED_CAPABILITIES
    # A PUBLIC device attempting a dangerous/deploy action never gets a
    # direct ALLOW even if somehow present in an effective set -- the
    # only thing it may receive is a typed "ask a Trusted Device to
    # approve" signal (spec section 12).
    requires_trusted_approval = (
        device_trust is DeviceTrustLevel.PUBLIC and capability in _AUTHORITY_REQUIRED_CAPABILITIES
    )

    if requires_trusted_approval:
        return PolicyDecision(
            capability=capability, allowed=False,
            reason="PUBLIC device cannot directly execute a dangerous/deploy capability -- requires a Trusted Device to approve",
            effective_mode=mode, device_trust=device_trust, requires_reauthentication=requires_reauth,
            requires_authority=requires_authority, requires_trusted_device_approval=True,
        )
    if not in_effective_set:
        return PolicyDecision(
            capability=capability, allowed=False,
            reason=f"{capability.value} is not in the effective capability set for device_trust={device_trust.value}, mode={mode.value}",
            effective_mode=mode, device_trust=device_trust, requires_reauthentication=requires_reauth,
            requires_authority=requires_authority, requires_trusted_device_approval=False,
        )
    return PolicyDecision(
        capability=capability, allowed=True,
        reason=(
            f"{capability.value} is policy-eligible; a validated ReauthGrant is still required before execution"
            if requires_reauth else "permitted by Relay security policy"
        ),
        effective_mode=mode, device_trust=device_trust, requires_reauthentication=requires_reauth,
        requires_authority=requires_authority, requires_trusted_device_approval=False,
    )


# ── Server-controlled session TTL / inactivity policy (spec sections 9-10) ──
# Named, server-controlled, conservative V1 defaults -- never taken
# from caller/request input.

TRUSTED_DEVICE_MAX_SESSION_SECONDS = 12 * 3600       # 12 hours
PUBLIC_DEVICE_MAX_SESSION_SECONDS = 2 * 3600         # 2 hours -- materially shorter than Trusted
MOBILE_REVIEW_MAX_SESSION_SECONDS = 8 * 3600         # 8 hours

TRUSTED_DEVICE_INACTIVITY_SECONDS = 2 * 3600         # 2 hours idle
PUBLIC_DEVICE_INACTIVITY_SECONDS = 5 * 60            # 5 minutes idle -- short, per threat model (shared/borrowed computer)
MOBILE_REVIEW_INACTIVITY_SECONDS = 30 * 60           # 30 minutes idle

_MAX_SESSION_SECONDS_BY_MODE: dict[RelayMode, int] = {
    RelayMode.TRUSTED_DEVICE: TRUSTED_DEVICE_MAX_SESSION_SECONDS,
    RelayMode.PUBLIC_DEVICE: PUBLIC_DEVICE_MAX_SESSION_SECONDS,
    RelayMode.MOBILE_REVIEW: MOBILE_REVIEW_MAX_SESSION_SECONDS,
}

_INACTIVITY_SECONDS_BY_MODE: dict[RelayMode, int] = {
    RelayMode.TRUSTED_DEVICE: TRUSTED_DEVICE_INACTIVITY_SECONDS,
    RelayMode.PUBLIC_DEVICE: PUBLIC_DEVICE_INACTIVITY_SECONDS,
    RelayMode.MOBILE_REVIEW: MOBILE_REVIEW_INACTIVITY_SECONDS,
}


# A device's trust level bounds which Relay modes its OWN sessions may
# legitimately run in -- a PUBLIC device can never carry a
# TRUSTED_DEVICE-mode session (spec section 2's canonical example:
# "PUBLIC device + TRUSTED_DEVICE session request => DENY"). Defined
# here (used by both session CREATION below and session VALIDATION
# further down) so both enforce the identical rule.
_ALLOWED_MODES_BY_DEVICE_TRUST: dict[DeviceTrustLevel, frozenset[RelayMode]] = {
    DeviceTrustLevel.TRUSTED: frozenset({RelayMode.TRUSTED_DEVICE, RelayMode.PUBLIC_DEVICE, RelayMode.MOBILE_REVIEW}),
    DeviceTrustLevel.PUBLIC: frozenset({RelayMode.PUBLIC_DEVICE, RelayMode.MOBILE_REVIEW}),
}


def create_relay_session(conn, *, device_id: str, mission_id: str, authenticated_user_id: str, mode: RelayMode, now_fn=_default_clock) -> RelaySession:
    """The security-authoritative, and ONLY normal-production, session-
    creation entrypoint (spec section 9; hardened 15.12.1 item 7) --
    `ttl_seconds` is ALWAYS derived from the server-controlled
    `_MAX_SESSION_SECONDS_BY_MODE` table for the requested mode, never
    accepted from a caller/request argument, and there is no
    `ttl_seconds` parameter here at all to accept one. (The lower-
    level `orca.mission.relay_store._create_session_with_explicit_ttl()`
    is an internal/test-only primitive, not exported for ordinary use
    -- see that function's own docstring.)

    Also enforces the device/mode compatibility invariant AT CREATION
    TIME (spec section 2), not merely at later read-validation time: a
    PUBLIC device can never be given a TRUSTED_DEVICE-mode session,
    regardless of what the caller requests."""
    from orca.mission.relay_store import _create_session_with_explicit_ttl

    device = get_device(conn, device_id)
    if device is None or device.user_id != authenticated_user_id:
        raise RelayAccessDeniedError(f"device {device_id} is not owned by the authenticated user")
    if mode not in _ALLOWED_MODES_BY_DEVICE_TRUST.get(device.trust_level, frozenset()):
        raise RelayAccessDeniedError(
            f"device trust_level={device.trust_level.value} cannot be granted a {mode.value} Relay session -- "
            f"a client cannot gain privilege merely by selecting a more privileged RelayMode string."
        )

    ttl_seconds = _MAX_SESSION_SECONDS_BY_MODE[mode]
    return _create_session_with_explicit_ttl(
        conn, device_id=device_id, mission_id=mission_id, authenticated_user_id=authenticated_user_id,
        mode=mode, ttl_seconds=ttl_seconds, now_fn=now_fn,
    )


# ── Session security validation (spec section 11) ────────────────────

class SecuritySessionStatus(Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    INACTIVITY_EXPIRED = "INACTIVITY_EXPIRED"
    DEVICE_MODE_MISMATCH = "DEVICE_MODE_MISMATCH"
    DEVICE_REVOKED = "DEVICE_REVOKED"


def evaluate_session_security(
    session: RelaySession, device: RelayDevice, *, now: datetime | None = None,
) -> SecuritySessionStatus:
    """One shared, non-scattered security-validity check (spec section
    11) -- combines Phase 15.11's own revoked/expired derivation with
    inactivity and mode/device-trust-compatibility checks. Does NOT
    weaken any Phase 15.11 invariant: REVOKED and EXPIRED are checked
    first and take priority exactly as `orca.mission.relay_store
    .session_status()` already defines them."""
    now = now or _default_clock()
    base_status = _session_status(session, now=now)
    if base_status is RelaySessionStatus.REVOKED:
        return SecuritySessionStatus.REVOKED
    if base_status is RelaySessionStatus.EXPIRED:
        return SecuritySessionStatus.EXPIRED
    if device.is_revoked:
        return SecuritySessionStatus.DEVICE_REVOKED
    if session.mode not in _ALLOWED_MODES_BY_DEVICE_TRUST.get(device.trust_level, frozenset()):
        return SecuritySessionStatus.DEVICE_MODE_MISMATCH

    inactivity_limit = _INACTIVITY_SECONDS_BY_MODE[session.mode]
    idle_for = now - _parse_iso(session.last_seen_at)
    if idle_for >= timedelta(seconds=inactivity_limit):
        return SecuritySessionStatus.INACTIVITY_EXPIRED
    return SecuritySessionStatus.ACTIVE


def require_security_valid_session(
    conn, session_id: str, *, authenticated_user_id: str, now_fn=_default_clock,
) -> tuple[RelaySession, RelayDevice]:
    """Ownership-checked, then full security-validity-checked session
    load. Raises `SessionSecurityInvalidError` (carrying the precise
    `SecuritySessionStatus`) for anything short of ACTIVE. An
    inactivity-expired session cannot be revived merely by touching it
    -- exactly like an absolute-expiry-expired one (spec section 10) --
    because this function is called BEFORE any touch/heartbeat write
    is ever issued (see `touch_relay_session_securely()` below)."""
    session = get_session_for_user(conn, session_id, authenticated_user_id=authenticated_user_id)
    device = get_device(conn, session.device_id)
    if device is None or device.user_id != authenticated_user_id:
        raise RelayAccessDeniedError(f"device {session.device_id} bound to session {session_id} is not owned by the authenticated user")

    now = now_fn()
    status = evaluate_session_security(session, device, now=now)
    if status is not SecuritySessionStatus.ACTIVE:
        raise SessionSecurityInvalidError(f"Relay session {session_id} security status is {status.value}", status=status)
    return session, device


def touch_relay_session_securely(conn, session_id: str, *, authenticated_user_id: str, now_fn=_default_clock) -> RelaySession:
    """The security-authoritative heartbeat entrypoint (15.12.1 item 8)
    -- validates the FULL Phase 15.12 security status (including
    inactivity and device/mode compatibility) BEFORE issuing any
    `last_seen_at` write. An inactivity-expired session's `last_seen_at`
    is therefore NEVER rewritten by this function -- `require_security_
    valid_session()` raises first, and the underlying
    `orca.mission.relay_store.touch_session()` UPDATE is never reached.
    This closes the exact adversarial scenario the 15.12 evidence had
    NOT actually proven: T0 create, no touch, T0 + inactivity_timeout +
    1s, attempt the normal heartbeat path -- must reject, and
    `last_seen_at` must remain unchanged."""
    require_security_valid_session(conn, session_id, authenticated_user_id=authenticated_user_id, now_fn=now_fn)
    return _touch_session_primitive(conn, session_id, authenticated_user_id=authenticated_user_id, now_fn=now_fn)


# ── Reauthentication (spec sections 7-8) -- real provenance ─────────
# NEVER a caller-supplied boolean, and NEVER a client-fabricatable
# object (15.12.1 item 3). Always derived from a REAL call to the
# existing orca.auth primitives (PBKDF2 password verification + RFC
# 6238 TOTP), and the resulting grant's authoritative record lives
# SERVER-SIDE, keyed by an opaque `secrets.token_urlsafe()` ID -- never
# reconstructable from public fields alone.

REAUTH_GRANT_TTL_SECONDS = 5 * 60  # 5 minutes -- short-lived, single-purpose, SERVER-CONTROLLED (no caller override)


@dataclass(frozen=True)
class ReauthGrant:
    """The ONLY thing ever handed back to a caller. Carries nothing but
    an opaque grant ID -- constructing one with a made-up ID (or
    copying the `grant_id` string incorrectly) produces an object that
    fails validation, because validation always looks up
    `_REAUTH_GRANTS[grant_id]` server-side; it never trusts anything
    about the `ReauthGrant` object itself beyond that one lookup key."""
    grant_id: str


@dataclass(frozen=True)
class _ReauthGrantRecord:
    """The REAL authoritative record, held only server-side in
    `_REAUTH_GRANTS`. Never serialized to a caller, never logged, never
    placed in Relay evidence. No credential value (password, TOTP
    code/secret) is ever stored here."""
    user_id: str
    relay_session_id: str | None
    issued_at: str
    expires_at: str
    factors_verified: tuple[str, ...]


# In-process grant store (spec section 15, item 3's Option A). A
# process restart empties this dict -- every outstanding grant becomes
# invalid, fail-closed (an unknown grant_id is exactly the same
# "invalid" outcome as a fabricated one). No durable schema is used or
# needed for this short-lived, purely server-side concept.
_REAUTH_GRANTS: dict[str, _ReauthGrantRecord] = {}


def verify_reauthentication(
    *, authenticated_user_id: str, password: str, totp_code: str | None = None,
    relay_session_id: str | None = None, now_fn=_default_clock,
) -> ReauthGrant:
    """Performs a REAL fresh reauthentication against the existing
    `orca.auth` primitives, for `authenticated_user_id` SPECIFICALLY --
    there is no `email`/alternate-identity parameter through which a
    caller could reauthenticate as a DIFFERENT account than the one
    already authenticated for this request (15.12.1 item 4: the
    account is looked up FROM `authenticated_user_id` via
    `orca.auth.store.get_user_by_id()`, never selected independently).
    Verifies the password for THAT user (`orca.auth.store
    .authenticate()`, which itself calls `orca.auth.crypto
    .verify_password()`, PBKDF2-SHA256) and, if THAT user's account has
    TOTP enabled, THAT user's `orca.auth.totp.verify_totp()` (RFC
    6238). Raises `ReauthenticationError` on ANY failure -- never
    returns a grant for a failed check.

    On success, issues a NEW server-side `_ReauthGrantRecord` (TTL
    always `REAUTH_GRANT_TTL_SECONDS` -- there is no `ttl_seconds`
    parameter here, 15.12.1 item 5) and returns only its opaque
    `ReauthGrant(grant_id=...)` handle. The password and TOTP code are
    used ONLY for this verification call; neither is ever stored on
    the grant record, logged, or placed in any Relay evidence."""
    from orca.auth.store import authenticate, get_totp_state, get_user_by_id
    from orca.auth.totp import verify_totp

    user = get_user_by_id(authenticated_user_id)
    if user is None:
        raise ReauthenticationError("reauthentication failed: no such authenticated user")

    verified = authenticate(user.email, password)
    if verified is None or verified.id != authenticated_user_id:
        raise ReauthenticationError("reauthentication failed: invalid password for the authenticated user")

    factors = ["password"]
    totp_state = get_totp_state(authenticated_user_id)
    if totp_state.get("enabled"):
        if not totp_code or not verify_totp(totp_state["secret"], totp_code, at_time=now_fn().timestamp()):
            raise ReauthenticationError("reauthentication failed: TOTP is enabled for this account and a valid current code is required")
        factors.append("totp")
    # else: password-only reauth is the currently available factor for
    # this account -- a genuine assurance-level limitation, disclosed
    # honestly rather than silently treated as equally strong.

    now_dt = now_fn()
    grant_id = _secrets.token_urlsafe(32)
    _REAUTH_GRANTS[grant_id] = _ReauthGrantRecord(
        user_id=authenticated_user_id, relay_session_id=relay_session_id, issued_at=now_dt.isoformat(),
        expires_at=(now_dt + timedelta(seconds=REAUTH_GRANT_TTL_SECONDS)).isoformat(),
        factors_verified=tuple(factors),
    )
    return ReauthGrant(grant_id=grant_id)


def is_reauth_grant_valid(
    grant, *, authenticated_user_id: str, relay_session_id: str | None = None, now: datetime | None = None,
) -> bool:
    """Validates SOLELY against the server-side `_REAUTH_GRANTS`
    store -- never against fields present on `grant` itself. `grant`
    may be an arbitrary object (a real `ReauthGrant`, `None`, a
    `SimpleNamespace`, a fabricated fake, anything) -- only
    `getattr(grant, "grant_id", None)` is read from it, and that value
    is used ONLY as a lookup key. If the key is missing from the
    store (never issued, already expired-and-any-future-cleanup,
    wrong ID, or the process restarted since it was issued), this
    returns `False` -- fail closed, never fail open on a plausible-
    looking object."""
    grant_id = getattr(grant, "grant_id", None)
    if not grant_id or not isinstance(grant_id, str):
        return False
    record = _REAUTH_GRANTS.get(grant_id)
    if record is None:
        return False
    now = now or _default_clock()
    if record.user_id != authenticated_user_id:
        return False
    if relay_session_id is not None and record.relay_session_id != relay_session_id:
        return False
    if now >= _parse_iso(record.expires_at):
        return False
    return True


def require_reauth_grant(
    grant, *, authenticated_user_id: str, relay_session_id: str | None = None, now_fn=_default_clock,
) -> ReauthGrant:
    if not is_reauth_grant_valid(grant, authenticated_user_id=authenticated_user_id, relay_session_id=relay_session_id, now=now_fn()):
        raise ReauthGrantInvalidError(
            "a valid, correctly-bound, unexpired, server-issued ReauthGrant is required for this action"
        )
    return grant


# ── Authoritative capability action gate (15.12.1 items 1-2) ────────

def authorize_relay_capability(
    conn, *, session_id: str, authenticated_user_id: str, capability: RelayCapability | str,
    reauth_grant: ReauthGrant | None = None, now_fn=_default_clock,
) -> PolicyDecision:
    """THE authoritative action gate. Unlike `check_capability()`
    (a pure query over caller-supplied `device_trust`/`mode`), this
    function:
      1. Loads the REAL `RelaySession`/`RelayDevice` from durable
         state via `require_security_valid_session()` -- ownership,
         revocation, absolute expiry, inactivity, and device/mode
         compatibility are all enforced here. A caller cannot claim
         `device_trust=TRUSTED`/`mode=TRUSTED_DEVICE` for a session
         that durably belongs to a PUBLIC device -- those values are
         never accepted as arguments at all.
      2. Computes the static policy decision from the LOADED
         `device.trust_level`/`session.mode`.
      3. If that capability requires reauthentication, validates
         `reauth_grant` against the REAL server-side grant store,
         bound to this exact `authenticated_user_id` and `session_id`
         -- a grant issued for a different user or a different
         session, or a fabricated/expired/unknown one, downgrades the
         decision to DENY.
    Raises `SessionSecurityInvalidError`/`RelayAccessDeniedError` (from
    step 1) for an invalid session -- the same fail-closed behavior as
    every other security-mode entrypoint."""
    session, device = require_security_valid_session(
        conn, session_id, authenticated_user_id=authenticated_user_id, now_fn=now_fn,
    )
    decision = check_capability(capability, device_trust=device.trust_level, mode=session.mode)
    if decision.allowed and decision.requires_reauthentication:
        grant_ok = is_reauth_grant_valid(
            reauth_grant, authenticated_user_id=authenticated_user_id, relay_session_id=session_id, now=now_fn(),
        )
        if not grant_ok:
            from dataclasses import replace as _replace
            decision = _replace(
                decision, allowed=False,
                reason=f"{decision.capability.value} requires a valid, real, server-issued ReauthGrant -- none was presented or it failed validation",
            )
    return decision


# ── Trusted-device enrollment (spec section 6; hardened 15.12.1 item 6) ──

def enroll_public_device(conn, *, authenticated_user_id: str, name: str | None = None, now_fn=_default_clock) -> RelayDevice:
    """PUBLIC enrollment remains low-friction (spec section 6) -- no
    reauthentication is required, matching the existing Phase 15.11
    `register_device()` behavior for PUBLIC devices exactly."""
    return _register_device_primitive(
        conn, authenticated_user_id=authenticated_user_id, trust_level=DeviceTrustLevel.PUBLIC, name=name, now_fn=now_fn,
    )


def enroll_trusted_device(
    conn, *, authenticated_user_id: str, reauth_grant: ReauthGrant, name: str | None = None, now_fn=_default_clock,
) -> RelayDevice:
    """The ONLY way to durably create a TRUSTED device row (spec
    section 6, hardened 15.12.1 item 6). Requires `reauth_grant` to
    validate against the REAL server-side grant store
    (`is_reauth_grant_valid()`), bound to `authenticated_user_id` --
    reauth for user A can never enroll a Trusted device for user B.
    An arbitrary object (a `SimpleNamespace(user_id=owner)`, a fake
    dataclass, a hand-built `ReauthGrant` with a made-up `grant_id`)
    fails this check every time, because validation never trusts
    anything on the object except a grant_id used purely as a lookup
    key -- `orca.mission.relay_store.register_device()` itself now
    unconditionally rejects TRUSTED trust, with NO proof-object
    parameter of any kind to satisfy; the actual INSERT happens only
    here, via the module-private `_insert_trusted_device_row()`, after
    this real validation succeeds."""
    if not is_reauth_grant_valid(reauth_grant, authenticated_user_id=authenticated_user_id, now=now_fn()):
        raise TrustedEnrollmentDeniedError(
            "TRUSTED device enrollment requires a valid, unexpired, real server-issued ReauthGrant bound to the authenticated user"
        )
    return _insert_trusted_device_row(conn, authenticated_user_id=authenticated_user_id, name=name, now_fn=now_fn)


# ── Session-control actions using Phase 15.12 validity (15.12.1 item 10) ──

def revoke_other_relay_session(
    conn, *, current_session_id: str, target_session_id: str, authenticated_user_id: str,
    reason: str | None = None, now_fn=_default_clock,
) -> RelaySession:
    """The security-authoritative wrapper around
    `orca.mission.relay_store.revoke_other_session()`: the CURRENT
    session must pass the FULL Phase 15.12 security-validity check
    (including inactivity and device/mode compatibility), not merely
    Phase 15.11's revoked/expired check -- an idle-expired session
    cannot act as a control context for revoking another session."""
    require_security_valid_session(conn, current_session_id, authenticated_user_id=authenticated_user_id, now_fn=now_fn)
    return _revoke_other_session_primitive(
        conn, current_session_id=current_session_id, target_session_id=target_session_id,
        authenticated_user_id=authenticated_user_id, reason=reason, now_fn=now_fn,
    )


def revoke_all_other_relay_sessions(
    conn, *, current_session_id: str, authenticated_user_id: str, now_fn=_default_clock,
) -> tuple[RelaySession, ...]:
    """Security-authoritative wrapper, same 15.12 validity requirement
    on the current session as `revoke_other_relay_session()`."""
    require_security_valid_session(conn, current_session_id, authenticated_user_id=authenticated_user_id, now_fn=now_fn)
    return _revoke_all_other_sessions_primitive(
        conn, current_session_id=current_session_id, authenticated_user_id=authenticated_user_id, now_fn=now_fn,
    )


def revoke_own_relay_session(
    conn, session_id: str, *, authenticated_user_id: str, reason: str | None = None, now_fn=_default_clock,
) -> RelaySession:
    """Self-revocation is deliberately MORE permissive than acting as
    a control context for another session (spec section 10's own
    allowance) -- an idle-expired or already-otherwise-invalid
    session may still revoke ITSELF (e.g. a deliberate logout on a
    device the user knows was left unattended past the inactivity
    window). This is a thin, clearly-named wrapper around the
    ownership-checked `orca.mission.relay_store.revoke_session()`
    with no additional 15.12 validity requirement -- documented here
    as the deliberate distinction from `revoke_other_relay_session()`/
    `revoke_all_other_relay_sessions()`, both of which DO require it."""
    return _revoke_session_primitive(
        conn, session_id, authenticated_user_id=authenticated_user_id, reason=reason, now_fn=now_fn,
    )


# ── Public-device indicator / security profile (spec sections 15-16) ──

@dataclass(frozen=True)
class SecurityProfile:
    mode: RelayMode
    device_trust: DeviceTrustLevel
    public_device: bool
    mobile_review: bool
    session_expires_at: str
    inactivity_deadline: str
    clipboard_export_allowed: bool
    download_allowed: bool
    restricted_capabilities: tuple[str, ...]


def build_security_profile(session: RelaySession, device: RelayDevice, *, now: datetime | None = None) -> SecurityProfile:
    """Every Public Device state surface must carry this explicit
    server-side metadata (spec section 15) -- never relying on visual
    styling alone. `browser enforcement` of clipboard/download policy
    is explicitly NOT claimed here (spec section 16/25) -- see
    DOWNLOAD_POLICY/CLIPBOARD_POLICY in the evidence checkpoint for
    that distinction."""
    now = now or _default_clock()
    effective = effective_capabilities(device_trust=device.trust_level, mode=session.mode)
    all_caps = frozenset(RelayCapability)
    restricted = tuple(sorted(c.value for c in (all_caps - effective)))
    inactivity_deadline = (_parse_iso(session.last_seen_at) + timedelta(seconds=_INACTIVITY_SECONDS_BY_MODE[session.mode])).isoformat()
    return SecurityProfile(
        mode=session.mode, device_trust=device.trust_level,
        public_device=(device.trust_level is DeviceTrustLevel.PUBLIC),
        mobile_review=(session.mode is RelayMode.MOBILE_REVIEW),
        session_expires_at=session.expires_at, inactivity_deadline=inactivity_deadline,
        clipboard_export_allowed=(RelayCapability.CLIPBOARD_EXPORT in effective),
        download_allowed=(RelayCapability.DOWNLOAD_CONTENT in effective),
        restricted_capabilities=restricted,
    )


# ── Sensitive file policy (spec section 17) ──────────────────────────
# Relay does not provide a file browser -- this is a deterministic
# policy PRIMITIVE for whenever a file reference/path crosses a Relay
# surface, not a claim that such a surface exists yet.

_SENSITIVE_PATH_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"(^|/)\.env(\..*)?$"),
    re.compile(r"\.pem$"),
    re.compile(r"\.key$"),
    re.compile(r"(^|/)id_rsa"),
    re.compile(r"(^|/)id_ed25519"),
    re.compile(r"credentials?[._-]"),
    re.compile(r"service[._-]?account.*\.json$"),
    re.compile(r"(^|/)kubeconfig$"),
    re.compile(r"\.p12$"),
    re.compile(r"\.pfx$"),
)


def is_sensitive_path(path: str) -> bool:
    return any(p.search(path) for p in _SENSITIVE_PATH_PATTERNS)


def file_access_capability_for(path: str, *, device_trust: DeviceTrustLevel) -> RelayCapability | None:
    """Returns `None` (deny/mask) for a sensitive path on a PUBLIC
    device; otherwise returns `RelayCapability.VIEW_FILES` for the
    caller to run through the policy layer as normal. On a Trusted
    device, a sensitive path is still policy-permitted at the FILE-
    ACCESS layer (spec section 17: 'Trusted may inspect project
    files') -- the separate, absolute raw-secret-VALUE prohibition
    (`orca.mission.relay_store._sanitize()`) is what keeps the actual
    secret content out of any Relay payload regardless."""
    if is_sensitive_path(path) and device_trust is DeviceTrustLevel.PUBLIC:
        return None
    return RelayCapability.VIEW_FILES


# ── Mobile Review state / secure snapshot (spec sections 5, 18, 23) ─
# (15.12.1 item 9: EVERY security-mode state-surface entrypoint now
# requires the Phase 15.12 security-valid session rule, enforced
# INSIDE build_relay_snapshot()'s own single REPEATABLE READ
# transaction via its `extra_validity_check` hook -- never a separate
# preceding query that could introduce a time-of-check/time-of-use
# gap.)

def _security_validity_check(session: RelaySession, device: RelayDevice, now: datetime) -> None:
    status = evaluate_session_security(session, device, now=now)
    if status is not SecuritySessionStatus.ACTIVE:
        raise SessionSecurityInvalidError(
            f"Relay session {session.id} security status is {status.value}, cannot produce a security-mode snapshot",
            status=status,
        )


def build_security_valid_relay_snapshot(
    conn, *, session_id: str, authenticated_user_id: str, now_fn=_default_clock,
) -> RelaySnapshot:
    """The security-authoritative snapshot entrypoint (15.12.1 item 9)
    -- identical to `orca.mission.relay_store.build_relay_snapshot()`
    except that it ALSO enforces the full Phase 15.12
    `evaluate_session_security()` rule (inactivity,
    device/mode-mismatch) inside that function's own single
    REPEATABLE READ transaction, via the `extra_validity_check` hook.
    An idle-expired Public OR Trusted session, or a corrupted PUBLIC-
    device/TRUSTED_DEVICE-mode session row, cannot produce a snapshot
    through this entrypoint. This is now the RECOMMENDED entrypoint for
    any security-mode-aware caller; the lower-level
    `relay_store.build_relay_snapshot()` (no `extra_validity_check`)
    remains available for Phase-15.11-only callers that do not need
    the stronger rule."""
    return build_relay_snapshot(
        conn, session_id=session_id, authenticated_user_id=authenticated_user_id, now_fn=now_fn,
        extra_validity_check=_security_validity_check,
    )


@dataclass(frozen=True)
class MobileReviewState:
    relay_session_id: str
    mission_id: str
    security_profile: SecurityProfile
    mission_state: str
    current_revision: str | None
    consistency_basis: str
    snapshot: RelaySnapshot  # the full underlying (already-sanitized) snapshot -- never re-queried independently


def build_mobile_review_state(
    conn, *, session_id: str, authenticated_user_id: str, now_fn=_default_clock,
) -> MobileReviewState:
    """Built EXCLUSIVELY from `build_security_valid_relay_snapshot()`
    (spec section 23) -- never a second, independently-queried
    representation of mission truth, and never merely
    Phase-15.11-ACTIVE: inactivity-expired or device/mode-mismatched
    sessions are rejected the same as revoked/expired ones, checked
    inside the SAME transaction as the snapshot itself."""
    now_dt = now_fn()
    snapshot = build_security_valid_relay_snapshot(
        conn, session_id=session_id, authenticated_user_id=authenticated_user_id, now_fn=now_fn,
    )
    session = get_session_for_user(conn, session_id, authenticated_user_id=authenticated_user_id)
    device = get_device(conn, session.device_id)
    profile = build_security_profile(session, device, now=now_dt)
    return MobileReviewState(
        relay_session_id=session.id, mission_id=snapshot.mission_id, security_profile=profile,
        mission_state=snapshot.mission_state, current_revision=snapshot.current_revision,
        consistency_basis=snapshot.consistency_basis, snapshot=snapshot,
    )
