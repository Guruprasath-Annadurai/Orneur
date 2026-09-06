# Phase 9.1 — Connector Authority Audit

Each item below states what was verified, how, and in which test(s).

## 1. Tenant isolation (registry, policy, cache, vector, Truth, Memory, Agent discovery)

- Registry: `tests/test_connector_tenant_isolation.py`, eval harness scenarios 1-2.
- Policy: `tests/test_connector_tenant_isolation.py::test_policy_denies_cross_tenant_even_if_capability_would_otherwise_allow`.
- Real DocStore vector isolation (two real tenants, shared connector_instance_id, real ChromaDB collections): `tests/test_connector_document_store.py::test_search_documents_vector_isolation_across_tenants`, eval harness scenario 13.
- Cache key isolation: `tests/test_connector_security.py::test_tenant_cache_key_isolated_across_tenants`, eval harness scenario 12.
- Truth Fabric bridge: evidence carries only the requesting connector's own provenance — no cross-tenant mixing possible since `connector_result_to_evidence()` operates on one already-tenant-scoped `ConnectorResult` at a time.
- Memory bridge: `tests/test_connector_truth_memory_bridges.py::test_memory_firewall_enforces_tenant_scope_isolation_for_connector_memory` — real `orca.memory.firewall.check()` call, both directions.
- Agent connector discovery: `tests/test_connector_agent_bridge.py::test_authorized_connector_tool_specs_only_shows_tenant_visible_healthy`.

**Result: no mocked-tenant-check-only path found. Every layer above was exercised with real code, not a stub returning a canned answer.**

## 2. Permission revocation E2E

`orca.connectors.lifecycle.PermissionRevocationTracker`: a cached entry's
recorded version becomes stale the instant `revoke()` bumps the current
version — `tests/test_connector_lifecycle_audit.py::test_permission_revocation_marks_previously_cached_entries_stale`.
This is the actual mechanism a caching layer must consult before serving
a cached read (`is_stale(connector_instance_id, cached_at_version)`);
Phase 9 does not yet have its OWN result cache to invalidate (no caching
layer was built — `tenant_cache_key()` only defines what a future
cache's key would be), so this is verified at the tracker-primitive
level, which is the actual unit of enforcement it would gate.

## 3. Deletion E2E

`orca.connectors.lifecycle.SimpleSyncStateStore.tombstone()`/`filter_out_tombstoned()`
verified against a REAL DocStore-returned result set (not a synthetic
dict) in `tests/test_connector_document_store.py::test_deleted_object_no_longer_retrievable_via_tombstone`
and eval harness scenario 14. A tombstoned object's real
`provider_object_id` (derived from `filename#chunk{idx}`, per the Phase 9
document-identity fix) is filtered from real retrieval output.

## 4. Credential redaction

Adversarial patterns tested: Bearer/API-key/token/password fields,
OpenAI `sk-`, GitHub `ghp_`, Slack `xox[baprs]-`, PEM private key blocks
— `tests/test_connector_security.py`. Verified absent from: audit
`operation` field (`record_audit_event()` always redacts — `tests/test_connector_lifecycle_audit.py::test_audit_event_records_and_redacts_operation`),
and structurally absent from `ConnectorResult`/`ConnectorAuditEvent`
(neither dataclass has a credential-shaped field —
`tests/test_connector_authority_regressions.py::test_connector_audit_event_schema_is_complete`).
`AgentTrace`/`WorldState`/`TruthResult`/Memory never receive a
`ConnectorCredentialRef`'s resolved value because no code path anywhere
in `orca/connectors/` ever resolves one to a real secret — it remains
opaque end to end (there being no real credential-consuming adapter yet
except DOCUMENT_STORE, which needs none).

## 5. Approval replay protection

`ApprovalBinding.matches()` requires exact match on connector instance,
resource scope, operation, AND a SHA-256 hash of sorted arguments —
verified: changed arguments rejected, different connector rejected,
expired binding rejected (`tests/test_connector_security.py`, eval
harness scenario 7). **APPROVAL_REPLAY_BYPASS = 0.**

## 6. OUTCOME_UNKNOWN

`FakeProviderState(simulate_network_break_after_send=True)` +
`fake_write()`: the write IS applied to fake remote state, but the
response is `OutcomeStatus.OUTCOME_UNKNOWN`, never `FAILURE` (which
would invite an unsafe blind retry of a non-idempotent write) or
`SUCCESS` (a claim the code cannot back) — `tests/test_connector_fake_provider.py`,
eval harness scenario 22. `AgentRuntime` treats a non-`SUCCESS` tool
result as `ERROR`/ambiguous and does not automatically retry (retries
are scoped to `_TRANSIENT_ERROR_CLASSES` — exception-based, not
`OUTCOME_UNKNOWN` results — so an ambiguous write is never blindly
retried by the generic retry path).

## 7. Cross-connector exfiltration

`authorize_cross_connector_flow()` authorizes purely on the
DESTINATION's configured `destination_allows_sensitivity` — the
canonical "malicious document instructs posting confidential data to
Slack channel X" attack has zero effect on the decision since source
content text is never consulted — `tests/test_connector_security.py`,
eval harness scenario 11. **CROSS_CONNECTOR_EXFILTRATION_BYPASS = 0.**

## 8. Federated partial failure

`FederatedSearchResult.is_partial` is True whenever anything was skipped
(unhealthy) or failed (policy-denied or adapter exception) — never
silently reported as complete — `tests/test_connector_federated_retrieval.py`,
eval harness scenarios 16-17.

## 9. Health/circuit + rate limiting

HEALTHY/DEGRADED routable; UNAUTHORIZED/OFFLINE/DISABLED unroutable;
RATE_LIMITED unroutable until its own `retry_after_s` cooldown elapses
(new in Phase 9.1 — previously the field existed on `ConnectorHealth`
but was never set or consulted, so a rate-limited connector never
recovered automatically; fixed in `orca/connectors/registry.py`) —
`tests/test_connector_registry_health.py`, `tests/test_connector_rate_limit_and_budget.py`.
Circuit breaker opens at 5 consecutive TRANSIENT failures.

**Disclosed limitation**: there is no cross-subagent shared token-bucket
/ collective-quota limiter for a single connector instance — the
circuit-breaker/health-state gate is a coarser, per-connector-instance
primitive (any caller sees the same unroutable state once it trips), not
a fine-grained concurrent-call cap. This bounds runaway retries (no
caller, including concurrent subagents, can push traffic to an
UNROUTABLE connector) but does not enforce, e.g., "at most N concurrent
in-flight calls." Building that is future work, not fabricated here.

## 10. Agent authority chain / AGENT_DIRECT_CONNECTOR_BYPASS

`orca/agent/runtime.py` has zero imports of `orca.connectors` (AST-
verified, `tests/test_connector_authority_regressions.py::test_agent_runtime_module_never_imports_connectors_directly`,
also `tests/test_connectors_fast_path.py`). The only way a connector
adapter is reachable from `AgentRuntime` is a plain callable registered
via `AgentToolRegistry.register()`, produced by
`orca.connectors.agent_bridge.make_connector_read_fn()`, which itself
re-runs `evaluate_connector_policy()` + `registry.is_routable()` inside
the callable — on top of `AgentRuntime._authorize()`'s own
Capability+Policy check that already ran before the callable is ever
invoked. **AGENT_DIRECT_CONNECTOR_BYPASS = 0.**

## 11. Connector discovery scope

`authorized_connector_tool_specs()` filters by tenant + health today.
**Disclosed limitation**: `ConnectorInstance` has no `workspace_id` or
per-principal scoping field, so workspace/project/principal-level
narrowing (beyond tenant) is not yet possible at the visibility layer —
`tests/test_connector_authority_regressions.py::test_connector_visibility_scoping_limitation_is_tenant_and_health_only`
documents this as current, real behavior rather than a false claim.
Execution still independently reauthorizes via
`evaluate_connector_policy()` regardless of what visibility narrowed to,
so this is a completeness gap in the pre-filter, not an authorization
bypass.

## 12. Truth Fabric authority / prompt injection

`ConnectorIdentity` is a frozen dataclass with no code path that parses
document/model text into it — `tests/test_connector_security.py::test_prompt_injection_in_remote_content_cannot_forge_identity`.
Connector evidence enters Truth Fabric as ordinary, contextually-
authoritative (never blindly trusted) `Evidence`/`EvidenceSource` pairs,
same as any other evidence source — remote text has no mechanism to
change a system prompt, grant a capability, select a credential, switch
tenant, or approve an action; none of those operations are even
reachable from `orca/truth/` or `orca/connectors/truth_bridge.py`.

## 13. Memory authority / UNVERIFIED_CONNECTOR_FACT_PROMOTION

`connector_result_to_memory_candidate()` returns a `MemoryCandidate`
value object only, never a `MemoryRecord`/`MemoryEpisode`, and the
module makes no call to any store/persist/promote function —
`tests/test_connector_authority_regressions.py`. **UNVERIFIED_CONNECTOR_FACT_PROMOTION = 0.**

## 14. Cache / vector isolation

`CONNECTOR_CACHE_SCOPE_LEAK = 0` (tenant-hashed cache keys, never
colliding across tenants — `tenant_cache_key()`).
`VECTOR_SCOPE_LEAK = 0` (real two-tenant DocStore round-trip, tenant-
namespaced ChromaDB collection names — see item 1).

## 15. Cancellation

Read cancellation and parent-`AgentRun` cancellation during a connector
action both verified real (asyncio `task.cancel()` interrupting an
in-flight connector tool call) —
`tests/test_connector_agent_runtime_e2e.py::test_cancellation_during_connector_read_returns_structured_cancelled_status`.
No new connector operation starts after cancellation because
`execute_async()`'s loop breaks out on `CancelledError` before advancing
to the next action. A write-cancellation-race specifically producing
`OUTCOME_UNKNOWN` is covered by item 6's fake-provider test (the
network-break simulation IS the write-in-flight-during-uncertainty
scenario; a real async write-cancellation race would need a real
external write provider, which does not exist in this codebase).

## 16. Budget accounting

`UNACCOUNTED_CONNECTOR_READ = 0`, `UNACCOUNTED_CONNECTOR_WRITE = 0`,
`DOUBLE_COUNTED_CONNECTOR_OPERATION = 0` — every connector action flows
through `AgentRuntime`'s single `self.ledger.reserve("tool_execution", 1)`
call site (one reservation per action attempt; retries reuse the same
reservation, never a new one) —
`tests/test_connector_rate_limit_and_budget.py::test_connector_action_accounted_exactly_once_in_tool_execution_budget`.

## 17. Fast path

`orca.cognitive.kernel`, `orca.truth.truth_fabric`, `orca.agent.runtime`,
`orca.agent.planner` never import `orca.connectors` — AST-verified,
`tests/test_connectors_fast_path.py`. A non-enterprise request never
enumerates the connector registry, queries a DocStore enterprise
collection, or runs federated retrieval, because none of that code is
even imported on that path.

## 18. Raw chain-of-thought storage

No connector module stores model reasoning/thinking content anywhere —
`ConnectorAuditEvent`, `ConnectorResult`, `ConnectorObservation` carry
only structured operational fields and normalized provider content,
never a model's internal reasoning trace. **RAW_CHAIN_OF_THOUGHT_STORAGE = 0.**
