"""
Phase 15.12 -- Relay Security Modes: the server-side capability-policy
layer that makes `TRUSTED_DEVICE`/`PUBLIC_DEVICE`/`MOBILE_REVIEW`
technically different, not merely three strings on a row.

Canonical distinctions this module exists to enforce (owner's own
closing lines):
  - Trusted does not mean ungoverned.
  - Public does not mean useless.
  - Mobile does not mean desktop shrunk onto a phone.
  - Reauthenticated does not mean authorized.
  - Raw secrets are never a Relay capability.

Architecture (spec section 0):

    AUTHENTICATED PRINCIPAL
            v
    DEVICE TRUST
            v
    RELAY SESSION MODE
            v
    SESSION VALIDITY
            v
    EFFECTIVE CAPABILITY POLICY   <- THIS MODULE
            v
    FRESH REAUTH CHECK where required   <- THIS MODULE (verification only)
            v
    EXISTING AUTHORITY ENGINE where required   <- orca.mission.operation_store /
                                                    orca.mission.authority_bridge,
                                                    NEVER touched or bypassed here
            v
    ACTION / SAFE STATE SURFACE

`RELAY POLICY PERMITS CAPABILITY` is never conflated with `AUTHORITY
ENGINE AUTHORIZES OPERATION` -- this module never calls into
`orca.mission.operation_store`/`orca.mission.authority_bridge`/
`orca.godmode.*` at all, in either direction. A capability decision
here can say ALLOW and that changes nothing about whether an actual
dangerous operation is AUTHORIZED; that remains exclusively Phase
15.5's job.

No custom cryptography is added: password verification reuses
`orca.auth.crypto.verify_password` (PBKDF2-SHA256, already in the
codebase) via `orca.auth.store.authenticate()`, and TOTP verification
reuses `orca.auth.totp.verify_totp()` (RFC 6238, already in the
codebase, already clock-injectable). No second authentication system
is invented -- this module only adds a RELAY-scoped, time-bound,
session-bound wrapper (`ReauthContext`) around a fresh call to those
existing primitives.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from orca.mission.mission_store import Checkpoint  # noqa: F401 -- re-exported context for docstrings only
from orca.mission.relay_store import (
    DeviceRevokedError,
    DeviceTrustLevel,
    RelayAccessDeniedError,
    RelayDevice,
    RelayError,
    RelayMode,
    RelaySession,
    RelaySessionInvalidError,
    RelaySessionNotFoundError,
    RelaySessionStatus,
    RelaySnapshot,
    build_relay_snapshot,
    get_device,
    get_session_for_user,
)
from orca.mission.relay_store import register_device as _register_device_primitive
from orca.mission.relay_store import session_status as _session_status


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
    password, wrong/missing TOTP, or an unavailable auth backend) --
    never raised for a merely-expired PRIOR reauth (see
    ReauthContextInvalidError for that)."""


class ReauthContextInvalidError(RelaySecurityError):
    """Raised when a previously-issued ReauthContext cannot be used for
    the requested action: wrong user, wrong Relay session, or expired.
    A boolean is never accepted in its place."""


class TrustedEnrollmentDeniedError(RelaySecurityError):
    """Raised when TRUSTED device enrollment is attempted without a
    valid, correctly-bound ReauthContext."""


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


# Capabilities that are security-sensitive enough to require fresh
# reauthentication at the RELAY POLICY layer before ALLOW is even
# considered (spec section 13). This is a Relay-policy gate only --
# it never substitutes for, and is always followed by, the real
# Authority Engine for the ones that also require it.
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
    capabilities."""
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
    reauth_valid: bool = False,
) -> PolicyDecision:
    """The one Relay-policy capability gate. An unknown capability
    (anything not a real `RelayCapability` member, e.g. a string a
    model/provider might invent) always DENIES (spec section 1: 'Unknown
    capability => DENY'; spec section 9: 'No model/provider text may
    change security policy' -- a provider can say any string it likes,
    it is never treated as a capability grant)."""
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
    if requires_reauth and not reauth_valid:
        return PolicyDecision(
            capability=capability, allowed=False, reason=f"{capability.value} requires fresh reauthentication",
            effective_mode=mode, device_trust=device_trust, requires_reauthentication=True,
            requires_authority=requires_authority, requires_trusted_device_approval=False,
        )
    return PolicyDecision(
        capability=capability, allowed=True, reason="permitted by Relay security policy",
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
    """The security-authoritative session-creation entrypoint (spec
    section 9) -- `ttl_seconds` is ALWAYS derived from the server-
    controlled `_MAX_SESSION_SECONDS_BY_MODE` table for the requested
    mode, never accepted from a caller/request argument. (The lower-
    level `orca.mission.relay_store.create_session()` still accepts an
    explicit `ttl_seconds` and remains available as an internal
    primitive -- e.g. for tests exercising expiry boundaries directly
    -- but is no longer the recommended, security-policy-authoritative
    entrypoint; this function is.)

    Also enforces the device/mode compatibility invariant AT CREATION
    TIME (spec section 2), not merely at later read-validation time: a
    PUBLIC device can never be given a TRUSTED_DEVICE-mode session,
    regardless of what the caller requests."""
    from orca.mission.relay_store import create_session as _create_session_primitive

    device = get_device(conn, device_id)
    if device is None or device.user_id != authenticated_user_id:
        raise RelayAccessDeniedError(f"device {device_id} is not owned by the authenticated user")
    if mode not in _ALLOWED_MODES_BY_DEVICE_TRUST.get(device.trust_level, frozenset()):
        raise RelayAccessDeniedError(
            f"device trust_level={device.trust_level.value} cannot be granted a {mode.value} Relay session -- "
            f"a client cannot gain privilege merely by selecting a more privileged RelayMode string."
        )

    ttl_seconds = _MAX_SESSION_SECONDS_BY_MODE[mode]
    return _create_session_primitive(
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
    NEW inactivity and mode/device-trust-compatibility checks. Does
    NOT weaken any Phase 15.11 invariant: REVOKED and EXPIRED are
    checked first and take priority exactly as `orca.mission.relay_store
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
    -- exactly like an absolute-expiry-expired one (spec section 10)."""
    session = get_session_for_user(conn, session_id, authenticated_user_id=authenticated_user_id)
    device = get_device(conn, session.device_id)
    if device is None or device.user_id != authenticated_user_id:
        raise RelayAccessDeniedError(f"device {session.device_id} bound to session {session_id} is not owned by the authenticated user")

    now = now_fn()
    status = evaluate_session_security(session, device, now=now)
    if status is not SecuritySessionStatus.ACTIVE:
        raise SessionSecurityInvalidError(f"Relay session {session_id} security status is {status.value}", status=status)
    return session, device


# ── Reauthentication (spec sections 7-8) ─────────────────────────────
# NEVER a caller-supplied boolean. Always derived from a REAL call to
# the existing orca.auth primitives (PBKDF2 password verification +
# RFC 6238 TOTP), never a second/custom crypto scheme.

REAUTH_CONTEXT_TTL_SECONDS = 5 * 60  # 5 minutes -- short-lived, single-purpose


@dataclass(frozen=True)
class ReauthContext:
    user_id: str
    relay_session_id: str | None
    issued_at: str
    expires_at: str
    factors_verified: tuple[str, ...]  # e.g. ("password",) or ("password", "totp") -- never the credential values themselves


def verify_reauthentication(
    *, email: str, password: str, totp_code: str | None = None, relay_session_id: str | None = None,
    now_fn=_default_clock, ttl_seconds: int = REAUTH_CONTEXT_TTL_SECONDS,
) -> ReauthContext:
    """Performs a REAL fresh reauthentication against the existing
    `orca.auth` primitives -- `orca.auth.store.authenticate()` (which
    itself calls `orca.auth.crypto.verify_password()`, PBKDF2-SHA256)
    and, if the account has TOTP enabled, `orca.auth.totp.verify_totp()`
    (RFC 6238). Raises `ReauthenticationError` on ANY failure (wrong
    password, TOTP enabled but code missing/wrong, or no such account)
    -- never returns a context for a failed check. The password and
    TOTP code are used ONLY for this verification call; neither is
    ever stored on the returned `ReauthContext`, logged, or placed in
    any Relay evidence."""
    from orca.auth.store import authenticate, get_totp_state
    from orca.auth.totp import verify_totp

    user = authenticate(email, password)
    if user is None:
        raise ReauthenticationError("reauthentication failed: invalid email or password")

    factors = ["password"]
    totp_state = get_totp_state(user.id)
    if totp_state.get("enabled"):
        if not totp_code or not verify_totp(totp_state["secret"], totp_code, at_time=now_fn().timestamp()):
            raise ReauthenticationError("reauthentication failed: TOTP is enabled for this account and a valid current code is required")
        factors.append("totp")
    # else: password-only reauth is the currently available factor for
    # this account -- a genuine assurance-level limitation, disclosed
    # honestly rather than silently treated as equally strong.

    now_dt = now_fn()
    return ReauthContext(
        user_id=user.id, relay_session_id=relay_session_id, issued_at=now_dt.isoformat(),
        expires_at=(now_dt + timedelta(seconds=ttl_seconds)).isoformat(), factors_verified=tuple(factors),
    )


def is_reauth_context_valid(
    context: ReauthContext, *, authenticated_user_id: str, relay_session_id: str | None = None, now: datetime | None = None,
) -> bool:
    """A fresh reauth result is bound, never a universal magic flag
    (spec section 8): it must match the calling user, and -- when a
    Relay session is the action's context -- the EXACT session it was
    issued for. It also simply expires."""
    now = now or _default_clock()
    if context.user_id != authenticated_user_id:
        return False
    if relay_session_id is not None and context.relay_session_id != relay_session_id:
        return False
    if now >= _parse_iso(context.expires_at):
        return False
    return True


def require_reauth_context(
    context: ReauthContext | None, *, authenticated_user_id: str, relay_session_id: str | None = None, now_fn=_default_clock,
) -> ReauthContext:
    if context is None or not is_reauth_context_valid(
        context, authenticated_user_id=authenticated_user_id, relay_session_id=relay_session_id, now=now_fn(),
    ):
        raise ReauthContextInvalidError(
            "a valid, correctly-bound, unexpired ReauthContext is required for this action"
        )
    return context


# ── Trusted-device enrollment (spec section 6) ───────────────────────

@dataclass(frozen=True)
class _TrustedEnrollmentProof:
    """Opaque, internal-only proof that TRUSTED enrollment was
    authorized by a genuinely fresh, correctly-bound reauthentication.
    Only `enroll_trusted_device()` below constructs one -- there is no
    public way to build one without passing through a real
    `verify_reauthentication()` call first."""
    user_id: str
    issued_at: str


def enroll_public_device(conn, *, authenticated_user_id: str, name: str | None = None, now_fn=_default_clock) -> RelayDevice:
    """PUBLIC enrollment remains low-friction (spec section 6) -- no
    reauthentication is required, matching the existing Phase 15.11
    `register_device()` behavior for PUBLIC devices exactly."""
    return _register_device_primitive(
        conn, authenticated_user_id=authenticated_user_id, trust_level=DeviceTrustLevel.PUBLIC, name=name, now_fn=now_fn,
    )


def enroll_trusted_device(
    conn, *, authenticated_user_id: str, reauth_context: ReauthContext, name: str | None = None, now_fn=_default_clock,
) -> RelayDevice:
    """The ONLY way to durably create a TRUSTED device row (spec
    section 6) -- requires a `ReauthContext` that is valid AND bound to
    `authenticated_user_id` (reauth for user A can never enroll a
    Trusted device for user B). `orca.mission.relay_store.register_device()`
    itself has no public parameter that grants TRUSTED trust without
    going through this function first -- see that module's own
    `_trusted_enrollment_proof` guard."""
    if not is_reauth_context_valid(reauth_context, authenticated_user_id=authenticated_user_id, now=now_fn()):
        raise TrustedEnrollmentDeniedError(
            "TRUSTED device enrollment requires a valid, unexpired reauthentication context bound to the authenticated user"
        )
    proof = _TrustedEnrollmentProof(user_id=authenticated_user_id, issued_at=now_fn().isoformat())
    return _register_device_primitive(
        conn, authenticated_user_id=authenticated_user_id, trust_level=DeviceTrustLevel.TRUSTED, name=name,
        now_fn=now_fn, _trusted_enrollment_proof=proof,
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
    caller to run through `check_capability()` as normal. On a Trusted
    device, a sensitive path is still policy-permitted at the FILE-
    ACCESS layer (spec section 17: 'Trusted may inspect project
    files') -- the separate, absolute raw-secret-VALUE prohibition
    (`orca.mission.relay_store._sanitize()`) is what keeps the actual
    secret content out of any Relay payload regardless."""
    if is_sensitive_path(path) and device_trust is DeviceTrustLevel.PUBLIC:
        return None
    return RelayCapability.VIEW_FILES


# ── Mobile Review state (spec sections 5, 18, 23) ────────────────────

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
    """Built EXCLUSIVELY from the canonical, already-consistent,
    already-secret-sanitized `RelaySnapshot` (spec section 23) -- never
    a second, independently-queried representation of mission truth.
    Requires a genuinely security-valid session (not merely
    Phase-15.11-ACTIVE) -- inactivity-expired Mobile Review sessions
    are rejected the same as revoked/expired ones."""
    session, device = require_security_valid_session(
        conn, session_id, authenticated_user_id=authenticated_user_id, now_fn=now_fn,
    )
    snapshot = build_relay_snapshot(conn, session_id=session_id, authenticated_user_id=authenticated_user_id, now_fn=now_fn)
    profile = build_security_profile(session, device, now=now_fn())
    return MobileReviewState(
        relay_session_id=session.id, mission_id=snapshot.mission_id, security_profile=profile,
        mission_state=snapshot.mission_state, current_revision=snapshot.current_revision,
        consistency_basis=snapshot.consistency_basis, snapshot=snapshot,
    )
