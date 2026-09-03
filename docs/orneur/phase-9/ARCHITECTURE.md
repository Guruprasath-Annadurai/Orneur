# Phase 9 — Connector Fabric Architecture

## Canonical flow

```
AgentGoal -> AgentPlanner -> AgentPlan (connector tool actions)
    -> AgentRuntime._authorize()
        -> Capability Engine (orca.agent.capability, pure membership)
        -> Policy Engine (orca.agent.policy, deterministic ALLOW/DENY/REQUIRE_APPROVAL)
    -> AgentToolRegistry.invoke()/invoke_async()
        -> connector tool fn (orca.connectors.agent_bridge.make_connector_read_fn)
            -> ConnectorRegistry.get_for_tenant()      (tenant lookup, TenantIsolationError on mismatch)
            -> evaluate_connector_policy()             (SECOND, independent policy check)
            -> registry.is_routable()                  (health/circuit-breaker gate)
            -> adapter (e.g. orca.connectors.document_store.search_documents)
                -> real backing system (DocStore, FakeProviderState, ...)
    -> ConnectorResult -> Observation -> WorldState update
```

Two independent authorization layers run on every connector action:
`orca.agent.policy` (generic agent-runtime policy) and
`orca.connectors.policy` (connector-specific tenant/capability/sensitivity
policy). Neither ever stands in for the other -- this is the same
"never trust a single check" discipline established by `orca.agent`'s own
policy/capability split in Phase 8.

## Package layout (`orca/connectors/`)

| Module | Responsibility |
|---|---|
| `contracts.py` | All typed dataclasses/enums -- no connector-specific dict ever crosses a system boundary. |
| `policy.py` | `evaluate_connector_policy()` -- deterministic, tenant-check-first. |
| `registry.py` | `ConnectorRegistry` -- tenant-scoped lookup, health/circuit-breaker tracking. |
| `document_store.py` | REAL_ADAPTER wrapping `orca.docs.store.DocStore`. |
| `fake_provider.py` | FAKE_TEST_PROVIDER for eval/tests -- idempotency + OUTCOME_UNKNOWN modeling. |
| `security.py` | Secret redaction, tenant-safe cache keys, approval binding, cross-connector flow authorization. |
| `agent_bridge.py` | Connector <-> `orca.agent` wiring: tool specs, tool visibility, defense-in-depth re-check. |
| `truth_bridge.py` | Connector result -> `orca.truth.contracts.Evidence`/`EvidenceSource` pairs. |
| `memory_bridge.py` | Connector result -> `orca.memory.contracts.MemoryCandidate` (TENANT scope). |
| `federated_retrieval.py` | Bounded, tenant-scoped, health-aware multi-connector search. |
| `audit.py` | Structured, redacted, tenant-filtered audit event log. |
| `lifecycle.py` | Sync/tombstone tracking, permission-revocation staleness. |
| `eval_harness.py` | 24 deterministic scenarios (spec §65-66). |
| `latency_bench.py` | Framework-overhead-only latency measurement (spec §68). |

## Why no new SourceType/MemoryScope was invented

`connector_result_to_evidence()` maps every connector family onto Truth
Fabric's EXISTING `SourceType` values (`UPLOADED_DOCUMENT` for high-
authority connector families, `WEB_COMMUNITY` for informal ones) rather
than adding a new enum value Truth Fabric's own authority/freshness logic
would not know how to weigh. Similarly, `connector_result_to_memory_candidate()`
activates `MemoryScope.TENANT`, a value already defined in Phase 5 as
"reserved contract surface for a future multi-tenant deployment" --
Phase 9 is that future; `orca.memory.firewall` needed zero changes to
enforce it correctly.
