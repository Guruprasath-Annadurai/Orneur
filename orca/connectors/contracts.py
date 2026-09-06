"""
Enterprise Connector Fabric typed contracts (Phase 9 spec §3). No
arbitrary connector-specific dict is ever the system boundary -- every
connector request/result flows through these typed dataclasses. Identity
(`ConnectorIdentity`) is never model-produced (spec §6) -- it is
constructed by the calling platform code from `orca.auth`'s existing
`User`/`org_id` primitives, before a connector request is ever built.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Connector taxonomy (spec §4) ──────────────────────────────────────────

class ConnectorType(str, Enum):
    DOCUMENT_STORE = "DOCUMENT_STORE"
    CODE_HOST = "CODE_HOST"
    MESSAGING = "MESSAGING"
    CALENDAR = "CALENDAR"
    TICKETING = "TICKETING"
    DATABASE = "DATABASE"
    CRM = "CRM"
    OBJECT_STORAGE = "OBJECT_STORAGE"
    INTERNAL_API = "INTERNAL_API"


class ConnectorImplementationClass(str, Enum):
    """Spec §70's explicit honesty requirement -- every connector family
    must be classified as one of these, never silently implied to be
    more connected than it is."""
    REAL_ADAPTER = "REAL_ADAPTER"
    CONTRACT_ONLY = "CONTRACT_ONLY"
    FAKE_TEST_PROVIDER = "FAKE_TEST_PROVIDER"


class ConnectorCapabilityKind(str, Enum):
    CONNECTOR_READ = "CONNECTOR_READ"
    CONNECTOR_WRITE = "CONNECTOR_WRITE"
    CONNECTOR_SEARCH = "CONNECTOR_SEARCH"
    CONNECTOR_DELETE = "CONNECTOR_DELETE"


class DataSensitivity(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    PRIVATE = "PRIVATE"
    SENSITIVE = "SENSITIVE"


class ConnectorHealthState(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAUTHORIZED = "UNAUTHORIZED"
    RATE_LIMITED = "RATE_LIMITED"
    OFFLINE = "OFFLINE"
    DISABLED = "DISABLED"


# ── Identity (spec §6) ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class ConnectorIdentity:
    """Never model-produced -- constructed by platform code from
    `orca.auth.store.User`/`orca.auth.org_store` identity BEFORE any
    connector request exists. A model can never set/override any field
    here (structurally: this dataclass never appears as a field on
    `AgentAction`/`ToolSpec`, only as a parameter platform code passes
    directly into connector functions)."""
    tenant_id: str                     # = org_id, the existing real multi-tenancy identity (orca.auth.org_store)
    principal_id: str                  # = User.id
    workspace_id: str | None = None
    effective_permissions: frozenset[str] = field(default_factory=frozenset)


# ── Credential reference (spec §15, §18) ──────────────────────────────────

@dataclass(frozen=True)
class ConnectorCredentialRef:
    """An OPAQUE reference -- never the secret value itself. Only the
    connector execution boundary (orca.connectors.registry's adapter
    dispatch) resolves this to an actual credential; it never appears in
    a prompt, WorldState, Memory, TruthResult, or AgentTrace (spec §15)."""
    credential_ref_id: str
    auth_mode: str = "NONE"    # "OAUTH" | "API_TOKEN" | "SERVICE_ACCOUNT" | "DB_CREDENTIALS" | "SIGNED_INTERNAL_TOKEN" | "NONE"


# ── Connector scope (spec §8) ──────────────────────────────────────────────

@dataclass(frozen=True)
class ConnectorScope:
    """Explicit, narrow scope -- never "the whole enterprise account."
    `resource_path` is connector-type-specific (a repo name, a Drive
    folder ID, a Slack channel ID, a schema.table, ...)."""
    resource_path: str = ""
    sub_scopes: frozenset[str] = field(default_factory=frozenset)


# ── Connector spec / instance (spec §5) ────────────────────────────────────

@dataclass
class ConnectorSpec:
    connector_type: ConnectorType
    implementation_class: ConnectorImplementationClass
    capabilities: frozenset[ConnectorCapabilityKind] = field(default_factory=frozenset)
    default_sensitivity: DataSensitivity = DataSensitivity.INTERNAL


@dataclass
class ConnectorInstance:
    connector_instance_id: str = field(default_factory=lambda: _new_id("conn"))
    connector_type: ConnectorType = ConnectorType.DOCUMENT_STORE
    tenant_id: str = ""
    owner_principal_id: str = ""
    credential_ref: ConnectorCredentialRef | None = None
    enabled_capabilities: frozenset[ConnectorCapabilityKind] = field(default_factory=lambda: frozenset({ConnectorCapabilityKind.CONNECTOR_READ}))
    read_write_mode: str = "READ_ONLY"   # "READ_ONLY" | "READ_WRITE"
    health: ConnectorHealthState = ConnectorHealthState.HEALTHY
    scope: ConnectorScope = field(default_factory=ConnectorScope)
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def structurally_rejects_write(self) -> bool:
        """spec §9: a read-only connector must structurally reject writes
        -- never rely only on a remote API failure."""
        return self.read_write_mode != "READ_WRITE" or ConnectorCapabilityKind.CONNECTOR_WRITE not in self.enabled_capabilities


# ── Requests / results (spec §23-24) ────────────────────────────────────────

@dataclass
class ConnectorRequest:
    request_id: str = field(default_factory=lambda: _new_id("creq"))
    identity: ConnectorIdentity | None = None
    connector_instance_id: str = ""
    scope: ConnectorScope = field(default_factory=ConnectorScope)
    operation: str = ""
    arguments: dict = field(default_factory=dict)


@dataclass
class ConnectorReadRequest(ConnectorRequest):
    query: str = ""


@dataclass
class ConnectorWriteRequest(ConnectorRequest):
    idempotency_key: str | None = None


@dataclass
class ConnectorObjectRef:
    """Every remote object retains real identity (spec §26) -- never just
    a display name."""
    connector_instance_id: str = ""
    provider_object_id: str = ""
    resource_scope: str = ""
    version: str | None = None
    last_modified: str | None = None


class OutcomeStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"    # spec §13: never report FAILED when external success is genuinely unknown


@dataclass
class ConnectorResult:
    request_id: str = ""
    status: OutcomeStatus = OutcomeStatus.FAILURE
    object_refs: list[ConnectorObjectRef] = field(default_factory=list)
    normalized_content: list[dict] = field(default_factory=list)   # typed EnterpriseX records, as plain dicts for transport
    sensitivity: DataSensitivity = DataSensitivity.INTERNAL
    error_class: str | None = None
    latency_ms: float = 0.0


@dataclass
class ConnectorObservation:
    observation_id: str = field(default_factory=lambda: _new_id("cobs"))
    request_id: str = ""
    connector_instance_id: str = ""
    status: str = "OK"
    facts: list[str] = field(default_factory=list)
    provenance: list[ConnectorObjectRef] = field(default_factory=list)
    sensitivity: DataSensitivity = DataSensitivity.INTERNAL


# ── Policy (spec §11) ────────────────────────────────────────────────────

class ConnectorPolicyDecisionState(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


@dataclass
class ConnectorPolicyDecision:
    state: ConnectorPolicyDecisionState = ConnectorPolicyDecisionState.DENY
    reasons: list[str] = field(default_factory=list)


# ── Audit (spec §54) ─────────────────────────────────────────────────────

@dataclass
class ConnectorAuditEvent:
    event_id: str = field(default_factory=lambda: _new_id("caudit"))
    tenant_id: str = ""
    principal_id: str = ""
    connector_instance_id: str = ""
    operation: str = ""
    read_write: str = "READ"
    policy_decision: str = ""
    approval_ref: str | None = None
    result_status: str = ""
    timestamp: str = field(default_factory=_now_iso)
    trace_id: str | None = None


# ── Health / sync (spec §19, §51) ───────────────────────────────────────────

@dataclass
class ConnectorHealth:
    connector_instance_id: str = ""
    state: ConnectorHealthState = ConnectorHealthState.HEALTHY
    consecutive_failures: int = 0
    last_checked_at: str = field(default_factory=_now_iso)
    retry_after_s: float | None = None


@dataclass
class ConnectorSyncState:
    connector_instance_id: str = ""
    sync_cursor: str | None = None
    last_sync_at: str | None = None
    tombstoned_object_ids: list[str] = field(default_factory=list)
