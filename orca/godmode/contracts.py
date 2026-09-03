"""
Dual-Mode Godmode typed contracts (Phase 10). No arbitrary dict is ever
the boundary for an elevation request, lease, session, or audit event.

Canonical rule (spec §2):

    effective_authority = normal_authority + valid_elevated_lease_scope

never `effective_authority = unrestricted`. A `CapabilityLease` is
always narrow (one capability, one resource scope, one operation scope,
one expiry) -- there is no "grant everything" lease shape representable
in this module at all (no wildcard capability/resource/operation field
exists on `CapabilityLease`).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def now_iso() -> str:
    """The one trusted clock abstraction (spec §49) -- every expiry/issued-at
    timestamp in this package is produced here, never from a client-
    supplied value, so clock skew from an external caller can never
    extend or shrink validity."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


# ── Authority levels (spec §4) ───────────────────────────────────────────
# Level alone NEVER grants a capability -- it is context/policy input
# only. Named distinctly from "ultra" (a commercial/model-tier term,
# confirmed unrelated by CURRENT_AUTHORITY_ARCHITECTURE.md) to avoid
# conflating two unrelated concepts.

class AuthorityLevel(str, Enum):
    UNTRUSTED = "UNTRUSTED"
    NORMAL = "NORMAL"
    PRIVILEGED = "PRIVILEGED"
    ELEVATED = "ELEVATED"
    GODMODE = "GODMODE"


_LEVEL_RANK: dict[AuthorityLevel, int] = {
    AuthorityLevel.UNTRUSTED: 0,
    AuthorityLevel.NORMAL: 1,
    AuthorityLevel.PRIVILEGED: 2,
    AuthorityLevel.ELEVATED: 3,
    AuthorityLevel.GODMODE: 4,
}


def level_rank(level: AuthorityLevel) -> int:
    return _LEVEL_RANK[level]


# ── Capability domain (which existing Capability Engine a lease targets) ──

class CapabilityDomain(str, Enum):
    AGENT = "AGENT"            # orca.agent.contracts.Capability values
    CONNECTOR = "CONNECTOR"    # orca.connectors.contracts.ConnectorCapabilityKind values
    FILE = "FILE"              # a narrow filesystem write/read root
    PROCESS = "PROCESS"        # disabled in Phase 10 -- see file_elevation.py/process docs


# ── Issuer authority (spec §9) -- never model/tool/Court/memory ─────────

class LeaseIssuerClass(str, Enum):
    HUMAN_APPROVAL = "HUMAN_APPROVAL"
    SYSTEM_POLICY = "SYSTEM_POLICY"
    ADMIN_POLICY = "ADMIN_POLICY"


# ── Elevated capability request (model may PROPOSE, never activate) ─────

@dataclass
class ElevatedCapabilityRequest:
    request_id: str = field(default_factory=lambda: _new_id("elevreq"))
    principal_id: str = ""
    tenant_id: str = ""
    capability_domain: CapabilityDomain = CapabilityDomain.AGENT
    capability: str = ""
    resource_scope: str = ""
    operation_scope: str = ""
    reason: str = ""
    requested_duration_s: float = 300.0
    risk: str = "LOW"
    run_reference: str | None = None
    created_at: str = field(default_factory=now_iso)


class ArgumentBindingMode(str, Enum):
    """Phase 10.1 spec §13: wildcard/argument-agnostic behavior must be
    EXPLICIT and policy-controlled -- an empty/missing arguments_hash
    must never be silently interpreted as 'any arguments allowed'.

    EXACT_ARGUMENTS (the default): the action's canonicalized arguments
    must hash to EXACTLY the bound value, or the action is denied.

    SCOPED_ARGUMENTS: an explicit, distinct policy meaning "this lease
    intentionally authorizes a bounded CLASS of repeated operations
    within its resource/operation scope, not one exact argument
    payload" (spec §13's example: FILE_WRITE inside one exact temp
    directory for N uses, where file content legitimately varies call
    to call). Never the default -- an issuer must explicitly request it.
    """
    EXACT_ARGUMENTS = "EXACT_ARGUMENTS"
    SCOPED_ARGUMENTS = "SCOPED_ARGUMENTS"


# ── Approval (spec §10) -- binds to the EXACT action, never reusable ────

@dataclass(frozen=True)
class GodmodeApproval:
    approval_id: str
    principal_id: str
    tenant_id: str
    capability_domain: CapabilityDomain
    capability: str
    resource_scope: str
    operation_scope: str
    arguments_hash: str
    duration_s: float
    reason: str
    approved_by: str
    expires_at: str
    binding_mode: ArgumentBindingMode = ArgumentBindingMode.EXACT_ARGUMENTS


# ── Capability lease (spec §6-7) -- always narrow ────────────────────────

class LeaseRevocationState(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


@dataclass
class CapabilityLease:
    lease_id: str = field(default_factory=lambda: _new_id("lease"))
    principal_id: str = ""
    tenant_id: str = ""
    capability_domain: CapabilityDomain = CapabilityDomain.AGENT
    capability: str = ""                 # exactly one capability value -- never a list, never "*"
    resource_scope: str = ""             # exactly one scope path/resource id -- never "*"
    operation_scope: str = ""            # exactly one operation -- never "*"
    issued_at: str = field(default_factory=now_iso)
    expires_at: str = ""
    issuer: LeaseIssuerClass = LeaseIssuerClass.SYSTEM_POLICY
    issuer_id: str = ""
    reason: str = ""
    # Phase 10.1 (spec §4-6): binds the action PAYLOAD, on top of the
    # capability/resource/operation/tenant scope above. `None` only ever
    # occurs together with `binding_mode == SCOPED_ARGUMENTS` -- see
    # `is_argument_binding_consistent()` below, enforced at issuance.
    arguments_hash: str | None = None
    binding_mode: ArgumentBindingMode = ArgumentBindingMode.EXACT_ARGUMENTS
    approval_id: str | None = None
    max_uses: int | None = 1             # None only for the rare, explicitly-reviewed multi-use lease
    uses_remaining: int | None = 1
    delegable: bool = False              # spec §54: nondelegable by default
    nonce: str = field(default_factory=lambda: uuid.uuid4().hex)
    revocation_state: LeaseRevocationState = LeaseRevocationState.ACTIVE
    signature: str = ""                  # HMAC integrity tag -- see orca.godmode.integrity

    def is_wildcard(self) -> bool:
        """Structural guard used at issuance -- see issuance.py. Kept
        here as a pure, reusable predicate so no issuance path can skip
        it."""
        return any(v in ("*", "", "ALL", "all", "everything", "admin") for v in (self.capability, self.resource_scope, self.operation_scope))

    def is_argument_binding_consistent(self) -> bool:
        """Phase 10.1 spec §13: an EMPTY/missing `arguments_hash` must
        NEVER be silently treated as wildcard -- it is only ever valid
        together with an EXPLICIT `binding_mode == SCOPED_ARGUMENTS`.
        `EXACT_ARGUMENTS` (the default) REQUIRES a non-empty hash."""
        if self.binding_mode == ArgumentBindingMode.EXACT_ARGUMENTS:
            return bool(self.arguments_hash)
        return True  # SCOPED_ARGUMENTS may have a hash (for a class-fingerprint) or not


# ── Godmode session (spec §5) ────────────────────────────────────────────

class GodmodeSessionState(str, Enum):
    REQUESTED = "REQUESTED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    DENIED = "DENIED"
    TERMINATED = "TERMINATED"


@dataclass
class GodmodeSession:
    session_id: str = field(default_factory=lambda: _new_id("gmsess"))
    principal_id: str = ""
    tenant_id: str = ""
    requested_level: AuthorityLevel = AuthorityLevel.ELEVATED
    effective_level: AuthorityLevel = AuthorityLevel.NORMAL
    created_at: str = field(default_factory=now_iso)
    expires_at: str = ""
    reason: str = ""
    lease_ids: list[str] = field(default_factory=list)
    state: GodmodeSessionState = GodmodeSessionState.REQUESTED
    trace_id: str | None = None


# ── Elevated policy decision trace (spec §20) ────────────────────────────

class ElevatedPolicyDecisionState(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    ELEVATION_REQUIRED = "ELEVATION_REQUIRED"   # spec §37: distinct from a flat DENY


@dataclass
class ElevatedPolicyDecision:
    state: ElevatedPolicyDecisionState = ElevatedPolicyDecisionState.DENY
    normal_decision_state: str = ""
    lease_considered_id: str | None = None
    scope_match: bool = False
    argument_match: bool = False
    binding_mode: str = ""
    expiry_ok: bool = False
    revocation_ok: bool = False
    kill_switch_active: bool = False
    reasons: list[str] = field(default_factory=list)


# ── Elevated action class (spec §32) ─────────────────────────────────────

class ElevatedActionClass(str, Enum):
    NORMAL_ACTION = "NORMAL_ACTION"
    ELEVATED_ACTION = "ELEVATED_ACTION"


# ── Audit (spec §43) ──────────────────────────────────────────────────────

class ElevationAuditEventType(str, Enum):
    REQUEST = "REQUEST"
    APPROVAL = "APPROVAL"
    ISSUE = "ISSUE"
    ACTIVATE = "ACTIVATE"
    USE = "USE"
    DENY = "DENY"
    EXPIRE = "EXPIRE"
    REVOKE = "REVOKE"
    KILL_SWITCH_DENIAL = "KILL_SWITCH_DENIAL"


@dataclass
class ElevationAuditEvent:
    event_id: str = field(default_factory=lambda: _new_id("gmaudit"))
    event_type: ElevationAuditEventType = ElevationAuditEventType.REQUEST
    principal_id: str = ""
    tenant_id: str = ""
    lease_id: str | None = None
    capability: str = ""
    resource_scope: str = ""
    operation_scope: str = ""
    issuer: str | None = None
    timestamp: str = field(default_factory=now_iso)
    trace_id: str | None = None
    result: str = ""


class LeaseIssuanceError(ValueError):
    """Raised for any structural issuance violation (wildcard scope,
    disallowed issuer, missing/invalid approval binding) -- never a
    silently-degraded partial lease."""
