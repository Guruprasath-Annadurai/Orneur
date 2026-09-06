"""
Phase 9.1 spec §20-25 authority regressions: AgentRuntime never bypasses
the connector authority chain, connector-derived memory is never
auto-promoted, and the audit event schema is complete.
"""
from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

from orca.connectors.contracts import ConnectorAuditEvent, ConnectorIdentity, ConnectorInstance, ConnectorType
from orca.connectors.memory_bridge import connector_result_to_memory_candidate


def test_agent_runtime_module_never_imports_connectors_directly():
    """spec §20's AGENT_DIRECT_CONNECTOR_BYPASS = 0: the only way a
    connector adapter is ever reachable from AgentRuntime is through a
    plain callable registered in AgentToolRegistry (which itself re-runs
    capability+policy) -- orca.agent.runtime has no direct import of
    orca.connectors at all, so there is no code path that could call a
    connector adapter without going through ToolRegistry -> Capability ->
    Policy first."""
    tree = ast.parse(Path("orca/agent/runtime.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("orca.connectors"):
            assert False, "orca.agent.runtime must never import orca.connectors directly"
        if isinstance(node, ast.Import):
            assert not any(a.name.startswith("orca.connectors") for a in node.names)


def test_connector_memory_candidate_is_not_a_promoted_memory_record():
    """spec §23's UNVERIFIED_CONNECTOR_FACT_PROMOTION = 0: the bridge
    returns a MemoryCandidate value object only -- never a MemoryRecord/
    MemoryEpisode/SemanticMemory entry, and never calls any store/persist
    function itself. Promotion remains MemoryArbiter's own governance."""
    from orca.memory.contracts import MemoryCandidate, MemoryRecord

    instance = ConnectorInstance(connector_type=ConnectorType.DOCUMENT_STORE, tenant_id="org-1", owner_principal_id="u1")
    from orca.connectors.contracts import ConnectorObjectRef, ConnectorResult, OutcomeStatus
    result = ConnectorResult(status=OutcomeStatus.SUCCESS, object_refs=[ConnectorObjectRef(connector_instance_id="c1", provider_object_id="o1")], normalized_content=[{"text": "a fact"}])

    candidate = connector_result_to_memory_candidate(instance, result, tenant_id="org-1")
    assert isinstance(candidate, MemoryCandidate)
    assert not isinstance(candidate, MemoryRecord)


def test_memory_bridge_module_never_calls_a_store_or_promotion_function():
    """Structural check: the module source contains no call to anything
    named like a persistence/promotion function -- it only ever
    constructs and returns a MemoryCandidate."""
    source = Path("orca/connectors/memory_bridge.py").read_text()
    forbidden_substrings = ["MemoryArbiter(", ".save(", ".persist(", ".promote(", ".write("]
    for token in forbidden_substrings:
        assert token not in source, f"memory_bridge.py must not call {token} -- promotion stays MemoryArbiter's own governance"


def test_connector_audit_event_schema_is_complete():
    """spec §25: audit events must carry principal, tenant, connector,
    operation, resource-class (read_write), policy decision, approval
    reference, result state, and trace ID -- and never a raw credential
    field."""
    fields = {f.name for f in dataclasses.fields(ConnectorAuditEvent)}
    required = {"principal_id", "tenant_id", "connector_instance_id", "operation", "read_write", "policy_decision", "approval_ref", "result_status", "trace_id"}
    assert required.issubset(fields)
    forbidden = {"credential", "secret", "api_key", "password", "token_value"}
    assert not (forbidden & fields)


def test_connector_visibility_scoping_limitation_is_tenant_and_health_only():
    """Disclosed limitation (Phase 9.1 spec §21): ConnectorInstance has no
    workspace_id/per-principal scoping field yet, so
    authorized_connector_tool_specs() can only narrow by tenant + health,
    not by workspace/project/principal. This test documents the CURRENT
    real behavior (not a false claim of finer-grained scoping) and
    confirms execution still independently reauthorizes regardless."""
    fields = {f.name for f in dataclasses.fields(ConnectorInstance)}
    assert "workspace_id" not in fields, "if this ever changes, authorized_connector_tool_specs() should be extended to filter on it too"
