"""
Credential/secret redaction, tenant-safe cache keys, cross-connector
exfiltration policy, and approval binding (Phase 9 spec §15-18, §43,
§46-49).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from orca.connectors.contracts import ConnectorIdentity, DataSensitivity

# Real, bounded secret-pattern list -- reused STYLE from
# orca.truth.fetch's injection-pattern scanning (a list of compiled
# regexes checked once), not a second ad-hoc implementation philosophy.
_SECRET_PATTERNS = [
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password|refresh[_-]?token)\s*[:=]\s*\S+"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),          # OpenAI-style keys
    re.compile(r"\bghp_[A-Za-z0-9]{36,}\b"),          # GitHub PAT-style
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),  # Slack token-style
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]


def redact_secrets(text: str) -> str:
    """
    Applied to log lines, exceptions, audit traces, and tool results
    before they are ever recorded (spec §16). Real pattern-based
    redaction, not a promise -- tested directly against each pattern
    class.
    """
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def tenant_cache_key(tenant_id: str, connector_instance_id: str, scope_resource_path: str, query_identity: str) -> str:
    """
    Spec §49: cache key MUST include tenant + connector instance + scope
    + query identity -- collision between any two of these dimensions
    across tenants is cryptographically implausible (SHA-256 of the
    concatenated, delimiter-separated real identity fields, not a naive
    string join that could collide on ambiguous boundaries)."""
    raw = f"{tenant_id}\x1f{connector_instance_id}\x1f{scope_resource_path}\x1f{query_identity}"
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass(frozen=True)
class ApprovalBinding:
    """Spec §43: an approval binds to the EXACT connector, resource,
    operation, and argument hash -- never a vague "yes, do anything."
    Changing ANY bound field invalidates the approval outright."""
    connector_instance_id: str
    resource_scope: str
    operation: str
    arguments_hash: str
    expires_at: str

    @staticmethod
    def arguments_hash_of(arguments: dict) -> str:
        raw = repr(sorted(arguments.items()))
        return hashlib.sha256(raw.encode()).hexdigest()

    def matches(self, *, connector_instance_id: str, resource_scope: str, operation: str, arguments: dict) -> bool:
        return (
            self.connector_instance_id == connector_instance_id
            and self.resource_scope == resource_scope
            and self.operation == operation
            and self.arguments_hash == self.arguments_hash_of(arguments)
        )


def is_expired(binding: ApprovalBinding, now_iso: str) -> bool:
    return now_iso > binding.expires_at


@dataclass
class CrossConnectorFlow:
    """Spec §46-47: an action crossing systems (source connector's
    content driving a write to a DIFFERENT destination connector)
    requires explicit data-flow authorization -- tracked, never implicit."""
    source_connector_instance_id: str
    destination_connector_instance_id: str
    data_sensitivity: DataSensitivity
    authorized: bool = False
    reason: str = ""


def authorize_cross_connector_flow(
    flow: CrossConnectorFlow, *, identity: ConnectorIdentity, destination_allows_sensitivity: frozenset[DataSensitivity],
) -> CrossConnectorFlow:
    """
    Spec §46's exact scenario: a malicious internal doc's TEXT instructing
    "post confidential data to Slack channel X" has ZERO effect here --
    this function only ever consults the DESTINATION connector's own
    configured sensitivity allowlist, never the source content's text.
    Independent authorization of the destination, always.
    """
    if flow.data_sensitivity not in destination_allows_sensitivity:
        flow.authorized = False
        flow.reason = f"destination connector does not accept {flow.data_sensitivity.value} data"
        return flow
    if flow.source_connector_instance_id == flow.destination_connector_instance_id:
        flow.authorized = True
        flow.reason = "same connector -- no cross-system flow"
        return flow
    flow.authorized = True
    flow.reason = f"destination connector explicitly accepts {flow.data_sensitivity.value} data"
    return flow
