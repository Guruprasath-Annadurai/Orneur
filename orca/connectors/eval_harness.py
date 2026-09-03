"""
Connector Fabric evaluation harness (Phase 9 spec §65-66). Deterministic
-- no live model call, no fabricated scores; every scenario exercises
real connector-fabric code, matching the same discipline as
`orca.agent.eval_harness`/`orca.society.eval_harness`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from orca.connectors.audit import audit_events_for_tenant, record_audit_event, reset_audit_log_for_tests
from orca.connectors.contracts import (
    ConnectorCapabilityKind,
    ConnectorIdentity,
    ConnectorInstance,
    ConnectorReadRequest,
    ConnectorScope,
    ConnectorType,
    ConnectorWriteRequest,
    DataSensitivity,
    OutcomeStatus,
)
from orca.connectors.document_store import _scoped_session_id, search_documents
from orca.connectors.fake_provider import FakeProviderState, fake_read, fake_write
from orca.connectors.federated_retrieval import federated_search
from orca.connectors.lifecycle import PermissionRevocationTracker, SimpleSyncStateStore
from orca.connectors.policy import evaluate_connector_policy
from orca.connectors.registry import ConnectorRegistry, TenantIsolationError
from orca.connectors.security import ApprovalBinding, CrossConnectorFlow, authorize_cross_connector_flow, redact_secrets, tenant_cache_key


@dataclass
class Scenario:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class HarnessResult:
    total: int = 0
    passed: int = 0
    results: list[Scenario] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0


def _record(results, name, condition, detail=""):
    results.append(Scenario(name=name, passed=bool(condition), detail=detail))


def _instance(tenant_id="org-1", **kwargs):
    return ConnectorInstance(connector_type=ConnectorType.TICKETING, tenant_id=tenant_id, owner_principal_id="u1", **kwargs)


def run_all() -> HarnessResult:
    results: list[Scenario] = []
    reset_audit_log_for_tests()

    # 1. Tenant A cannot read tenant B's connector.
    registry = ConnectorRegistry()
    instance_b = _instance(tenant_id="org-B")
    registry.register(instance_b)
    try:
        registry.get_for_tenant("org-A", instance_b.connector_instance_id)
        _record(results, "tenant_a_cannot_read_tenant_b_connector", False)
    except TenantIsolationError:
        _record(results, "tenant_a_cannot_read_tenant_b_connector", True)

    # 2. Tenant A cannot even enumerate tenant B's instances.
    registry2 = ConnectorRegistry()
    registry2.register(_instance(tenant_id="org-A"))
    registry2.register(_instance(tenant_id="org-B"))
    listed = registry2.list_for_tenant("org-A")
    _record(results, "tenant_cannot_enumerate_other_tenant_instances", all(i.tenant_id == "org-A" for i in listed) and len(listed) == 1)

    # 3. Policy denies cross-tenant unconditionally (never REQUIRE_APPROVAL).
    decision = evaluate_connector_policy(identity=ConnectorIdentity(tenant_id="org-A", principal_id="u1"), instance=instance_b, requested_capability=ConnectorCapabilityKind.CONNECTOR_READ)
    _record(results, "policy_denies_cross_tenant_unconditionally", decision.state.value == "DENY")

    # 4. Read-only connector structurally rejects write.
    ro_instance = _instance(tenant_id="org-1", read_write_mode="READ_ONLY", enabled_capabilities=frozenset({ConnectorCapabilityKind.CONNECTOR_READ}))
    _record(results, "read_only_connector_structurally_rejects_write", ro_instance.structurally_rejects_write() is True)

    # 5. Write requires explicit write capability even on READ_WRITE connector.
    rw_no_write_cap = _instance(tenant_id="org-1", read_write_mode="READ_WRITE", enabled_capabilities=frozenset({ConnectorCapabilityKind.CONNECTOR_READ}))
    decision5 = evaluate_connector_policy(identity=ConnectorIdentity(tenant_id="org-1", principal_id="u1"), instance=rw_no_write_cap, requested_capability=ConnectorCapabilityKind.CONNECTOR_WRITE)
    _record(results, "write_requires_explicit_capability", decision5.state.value == "DENY")

    # 6. Sensitive write requires approval.
    rw_instance = _instance(tenant_id="org-1", read_write_mode="READ_WRITE", enabled_capabilities=frozenset({ConnectorCapabilityKind.CONNECTOR_READ, ConnectorCapabilityKind.CONNECTOR_WRITE}))
    decision6 = evaluate_connector_policy(identity=ConnectorIdentity(tenant_id="org-1", principal_id="u1"), instance=rw_instance, requested_capability=ConnectorCapabilityKind.CONNECTOR_WRITE, sensitivity=DataSensitivity.SENSITIVE)
    _record(results, "sensitive_write_requires_approval", decision6.state.value == "REQUIRE_APPROVAL")

    # 7. Approval binding rejects changed arguments (forgery/replay).
    binding = ApprovalBinding(connector_instance_id="c1", resource_scope="s", operation="write", arguments_hash=ApprovalBinding.arguments_hash_of({"text": "ok"}), expires_at="2099-01-01T00:00:00Z")
    forged = binding.matches(connector_instance_id="c1", resource_scope="s", operation="write", arguments={"text": "EVIL"})
    _record(results, "approval_binding_rejects_argument_forgery", forged is False)

    # 8. Connector auth failure -> UNAUTHORIZED health, unroutable.
    registry3 = ConnectorRegistry()
    inst3 = _instance()
    registry3.register(inst3)
    registry3.record_failure(inst3.connector_instance_id, failure_class="AUTH_FAILURE")
    _record(results, "auth_failure_marks_unauthorized_unroutable", not registry3.is_routable(inst3.connector_instance_id))

    # 9. Rate limit -> RATE_LIMITED, unroutable.
    registry4 = ConnectorRegistry()
    inst4 = _instance()
    registry4.register(inst4)
    registry4.record_failure(inst4.connector_instance_id, failure_class="RATE_LIMIT")
    _record(results, "rate_limit_marks_unroutable", not registry4.is_routable(inst4.connector_instance_id))

    # 10. Circuit breaker opens after threshold transient failures.
    registry5 = ConnectorRegistry()
    inst5 = _instance()
    registry5.register(inst5)
    for _ in range(5):
        registry5.record_failure(inst5.connector_instance_id, failure_class="TRANSIENT")
    _record(results, "circuit_breaker_opens_after_threshold", not registry5.is_routable(inst5.connector_instance_id))

    # 11. Cross-connector exfiltration blocked by destination policy (malicious doc scenario).
    flow = CrossConnectorFlow(source_connector_instance_id="doc-1", destination_connector_instance_id="slack-1", data_sensitivity=DataSensitivity.SENSITIVE)
    flow_result = authorize_cross_connector_flow(flow, identity=ConnectorIdentity(tenant_id="org-1", principal_id="u1"), destination_allows_sensitivity=frozenset({DataSensitivity.INTERNAL}))
    _record(results, "cross_connector_exfiltration_blocked", flow_result.authorized is False)

    # 12. Cache key isolated across tenants.
    key_a = tenant_cache_key("org-A", "conn-1", "docs", "q")
    key_b = tenant_cache_key("org-B", "conn-1", "docs", "q")
    _record(results, "cache_key_tenant_isolated", key_a != key_b)

    # 13. Vector-search tenant isolation (real DocStore).
    from orca.docs.chunker import chunk_text
    from orca.docs.store import DocStore
    shared_id = "conn-eval-shared"
    inst_va = ConnectorInstance(connector_instance_id=shared_id, connector_type=ConnectorType.DOCUMENT_STORE, tenant_id="org-eval-A", owner_principal_id="u1", scope=ConnectorScope(resource_path="docs"))
    inst_vb = ConnectorInstance(connector_instance_id=shared_id, connector_type=ConnectorType.DOCUMENT_STORE, tenant_id="org-eval-B", owner_principal_id="u2", scope=ConnectorScope(resource_path="docs"))
    store_a = DocStore(session_id=_scoped_session_id(inst_va))
    store_a.add_chunks(chunk_text("Eval-only secret payload for tenant A.", doc_id="eval-secret", filename="eval-secret.txt"), doc_id="eval-secret", filename="eval-secret.txt")
    identity_vb = ConnectorIdentity(tenant_id="org-eval-B", principal_id="u2")
    vec_result = search_documents(identity_vb, inst_vb, ConnectorReadRequest(identity=identity_vb, connector_instance_id=shared_id, query="secret payload for tenant A"))
    _record(results, "vector_search_tenant_isolated", not any("tenant A" in c.get("text", "") for c in vec_result.normalized_content))

    # 14. Deleted-object-no-longer-retrievable (tombstone filtering).
    sync_store = SimpleSyncStateStore()
    sync_store.tombstone(shared_id, "deleted-obj")
    filtered = sync_store.filter_out_tombstoned(shared_id, [{"id": "deleted-obj"}, {"id": "kept-obj"}])
    _record(results, "deleted_object_no_longer_retrievable", filtered == [{"id": "kept-obj"}])

    # 15. Permission-revoked-after-caching -> stale.
    tracker = PermissionRevocationTracker()
    cached_version = tracker.current_version("conn-eval-1")
    tracker.revoke("conn-eval-1")
    _record(results, "permission_revoked_after_caching_is_stale", tracker.is_stale("conn-eval-1", cached_version))

    # 16. Federated search: partial results honestly reported.
    registry6 = ConnectorRegistry()
    inst6 = _instance(tenant_id="org-fed-1")
    registry6.register(inst6)
    for _ in range(5):
        registry6.record_failure(inst6.connector_instance_id, failure_class="TRANSIENT")
    fed_result = federated_search(ConnectorIdentity(tenant_id="org-fed-1", principal_id="u1"), registry6, "q", read_fns={})
    _record(results, "federated_search_reports_partial_honestly", fed_result.is_partial and inst6.connector_instance_id in fed_result.skipped_unhealthy)

    # 17. Federated search blocks explicit cross-tenant instance list.
    registry7 = ConnectorRegistry()
    inst7 = _instance(tenant_id="org-fed-B")
    registry7.register(inst7)
    try:
        federated_search(ConnectorIdentity(tenant_id="org-fed-A", principal_id="attacker"), registry7, "q", read_fns={}, connector_instance_ids=[inst7.connector_instance_id])
        _record(results, "federated_search_blocks_cross_tenant_explicit_list", False)
    except TenantIsolationError:
        _record(results, "federated_search_blocks_cross_tenant_explicit_list", True)

    # 18. Truth Fabric evidence integration preserves provenance.
    from orca.connectors.truth_bridge import connector_result_to_evidence
    from orca.connectors.contracts import ConnectorObjectRef, ConnectorResult
    ev_instance = ConnectorInstance(connector_type=ConnectorType.DOCUMENT_STORE, tenant_id="org-1", owner_principal_id="u1")
    ev_result = ConnectorResult(status=OutcomeStatus.SUCCESS, object_refs=[ConnectorObjectRef(connector_instance_id="c1", provider_object_id="o1", resource_scope="docs")], normalized_content=[{"text": "fact"}])
    pairs = connector_result_to_evidence(ev_instance, ev_result)
    _record(results, "truth_fabric_evidence_preserves_provenance", len(pairs) == 1 and pairs[0][0].origin_metadata["provider_object_id"] == "o1")

    # 19. Memory candidate preserves TENANT scope.
    from orca.connectors.memory_bridge import connector_result_to_memory_candidate
    from orca.memory.contracts import MemoryScope
    candidate = connector_result_to_memory_candidate(ev_instance, ev_result, tenant_id="org-1")
    _record(results, "memory_candidate_preserves_tenant_scope", candidate is not None and candidate.scope == MemoryScope.TENANT and candidate.scope_id == "org-1")

    # 20. AgentPlanner tool visibility: other tenant's connector never appears.
    from orca.connectors.agent_bridge import authorized_connector_tool_specs
    registry8 = ConnectorRegistry()
    inst_visible = ConnectorInstance(connector_type=ConnectorType.DOCUMENT_STORE, tenant_id="org-vis-A", owner_principal_id="u1", enabled_capabilities=frozenset({ConnectorCapabilityKind.CONNECTOR_READ}))
    inst_hidden = ConnectorInstance(connector_type=ConnectorType.DOCUMENT_STORE, tenant_id="org-vis-B", owner_principal_id="u2", enabled_capabilities=frozenset({ConnectorCapabilityKind.CONNECTOR_READ}))
    registry8.register(inst_visible)
    registry8.register(inst_hidden)
    specs = authorized_connector_tool_specs(registry8, ConnectorIdentity(tenant_id="org-vis-A", principal_id="u1"))
    _record(results, "planner_tool_visibility_excludes_other_tenant", not any(inst_hidden.connector_instance_id in t for t in specs) and any(inst_visible.connector_instance_id in t for t in specs))

    # 21. Idempotency key deduplicates a retried write.
    state = FakeProviderState()
    fake_instance = _instance(tenant_id="org-idem-1")
    fake_identity = ConnectorIdentity(tenant_id="org-idem-1", principal_id="u1")
    req = ConnectorWriteRequest(identity=fake_identity, connector_instance_id=fake_instance.connector_instance_id, arguments={"text": "once"}, idempotency_key="idem-eval-1")
    r1 = fake_write(fake_identity, fake_instance, req, state)
    r2 = fake_write(fake_identity, fake_instance, req, state)
    key = (fake_instance.tenant_id, fake_instance.connector_instance_id)
    _record(results, "idempotency_key_deduplicates_write", r1.status == OutcomeStatus.SUCCESS and r2.status == OutcomeStatus.SUCCESS and len(state.objects[key]) == 1)

    # 22. Network-break-after-send write reports OUTCOME_UNKNOWN, never FAILURE/SUCCESS-lied.
    state2 = FakeProviderState(simulate_network_break_after_send=True)
    req2 = ConnectorWriteRequest(identity=fake_identity, connector_instance_id=fake_instance.connector_instance_id, arguments={"text": "risky"}, idempotency_key="idem-eval-2")
    r3 = fake_write(fake_identity, fake_instance, req2, state2)
    _record(results, "network_break_write_reports_outcome_unknown", r3.status == OutcomeStatus.OUTCOME_UNKNOWN)

    # 23. Secret redaction across provider classes.
    redacted_ok = all(
        pat not in redact_secrets(text)
        for pat, text in [
            ("sk-abcdefghijklmnopqrstuvwxyz1234567890", "api_key: sk-abcdefghijklmnopqrstuvwxyz1234567890"),
            ("ghp_" + "a" * 36, "ghp_" + "a" * 36),
            ("xoxb-1234567890-abcdefghij", "xoxb-1234567890-abcdefghij"),
        ]
    )
    _record(results, "secret_redaction_across_provider_classes", redacted_ok)

    # 24. Audit log strictly tenant-filtered.
    record_audit_event(identity=ConnectorIdentity(tenant_id="org-aud-A", principal_id="u1"), instance=_instance(tenant_id="org-aud-A"), operation="read", read_write="READ", policy_decision="ALLOW", result_status="SUCCESS")
    record_audit_event(identity=ConnectorIdentity(tenant_id="org-aud-B", principal_id="u2"), instance=_instance(tenant_id="org-aud-B"), operation="read", read_write="READ", policy_decision="ALLOW", result_status="SUCCESS")
    events_a = audit_events_for_tenant("org-aud-A")
    _record(results, "audit_log_strictly_tenant_filtered", len(events_a) == 1 and events_a[0].tenant_id == "org-aud-A")

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    return HarnessResult(total=total, passed=passed, results=results)


if __name__ == "__main__":
    result = run_all()
    for scenario in result.results:
        status = "PASS" if scenario.passed else "FAIL"
        print(f"[{status}] {scenario.name} {scenario.detail}")
    print(f"\n{result.passed}/{result.total} scenarios passed ({result.pass_rate:.0%})")
