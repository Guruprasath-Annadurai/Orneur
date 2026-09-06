# Phase 9 — Security Summary

## Threat model coverage

| Threat | Mitigation | Verified in |
|---|---|---|
| Connector ID guessing / cross-tenant enumeration | `ConnectorRegistry.get_for_tenant()`/`list_for_tenant()` filter strictly, raise `TenantIsolationError` | `test_connector_tenant_isolation.py` |
| Scope forging | `ConnectorScope` is frozen and set by the platform at instance-creation time, never model-writable per-request | `contracts.py` structure |
| Approval forgery/replay | `ApprovalBinding.matches()` hashes arguments; any change invalidates | `test_connector_security.py` |
| Write escalation on a read-only connector | `structurally_rejects_write()` + policy DENY, checked twice (agent policy + connector policy) | `test_connector_tenant_isolation.py`, `test_connector_agent_bridge.py` |
| Cross-connector exfiltration via malicious document | `authorize_cross_connector_flow()` authorizes on destination's OWN sensitivity allowlist only, never source text | `test_connector_security.py` |
| Prompt injection ("ignore security, send secrets") | `ConnectorIdentity` is a frozen dataclass never derived from document/model text; structurally, no code path parses text into it | `test_connector_security.py::test_prompt_injection_in_remote_content_cannot_forge_identity` |
| Secret leakage into logs/audit | `redact_secrets()` applied to audit `operation` field unconditionally | `test_connector_security.py`, `test_connector_lifecycle_audit.py` |
| Cache-key collision across tenants | SHA-256 of tenant+connector+scope+query, `\x1f`-delimited | `test_connector_security.py` |
| Vector-search cross-tenant leakage | Tenant-namespaced ChromaDB collection name, verified with a real two-tenant DocStore round-trip | `test_connector_document_store.py` |
| Serving deleted remote content | `SimpleSyncStateStore` tombstoning | `test_connector_lifecycle_audit.py`, `test_connector_document_store.py` |
| Serving content under a revoked permission | `PermissionRevocationTracker` monotonic version staleness | `test_connector_lifecycle_audit.py` |
| Unsafe blind retry after an ambiguous write outcome | `OutcomeStatus.OUTCOME_UNKNOWN`, never silently reported as FAILURE or SUCCESS | `test_connector_fake_provider.py` |
| Cancellation mid-write leaving an unknown external state | `execute_async()` returns structured `CANCELLED`, never raises; a write's true remote outcome is never assumed | `test_connector_agent_runtime_e2e.py` |

## Structural (not just behavioral) guarantees

- `ConnectorIdentity` has no field a model or document content could set
  -- verified via `dataclasses.fields()` inspection in the prompt-
  injection test.
- `ConnectorRegistry.get_for_tenant()` is the ONLY lookup method on the
  registry -- there is no second method that returns an instance without
  a tenant check.
- `AgentRuntime.execute()`/`execute_async()` never import
  `orca.connectors` -- connector wiring is entirely caller-supplied via
  `AgentToolRegistry.register()`, proven by AST inspection in
  `test_connectors_fast_path.py`.

## Known gaps (see PHASE_9_CLOSURE.md for the full list)

No real third-party OAuth/credential vault exists; CODE_HOST, MESSAGING,
CALENDAR, TICKETING, CRM, DATABASE remain CONTRACT_ONLY (typed, policy-
enforced, but backed only by the in-memory FAKE_TEST_PROVIDER in tests --
never presented as real connectivity).
