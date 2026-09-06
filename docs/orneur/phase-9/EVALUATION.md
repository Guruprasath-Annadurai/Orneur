# Phase 9 — Evaluation

## Deterministic eval harness (`orca/connectors/eval_harness.py`)

24/24 scenarios pass (100%), covering spec §65-66's required families:
tenant isolation (lookup, enumeration, policy), read/write capability
separation, sensitive-write approval, approval-forgery rejection, health/
circuit-breaker states (auth failure, rate limit, threshold), cross-
connector exfiltration, cache-key isolation, real-DocStore vector-search
tenant isolation, tombstone filtering, permission-revocation staleness,
federated search (partial honesty + cross-tenant block), Truth Fabric
evidence provenance, Memory TENANT-scope preservation, AgentPlanner tool
visibility, idempotency deduplication, OUTCOME_UNKNOWN, secret redaction,
audit log tenant filtering.

Run: `.venv/bin/python -m orca.connectors.eval_harness`

## Pytest suite

75 tests across 10 files (`tests/test_connector_*.py`,
`tests/test_connectors_fast_path.py`), all passing -- see
PHASE_9_CLOSURE.md for the exact file list and counts. Includes a real
(non-mocked) `AgentGoal -> AgentPlan -> AgentRuntime -> connector ->
DocStore -> WorldState` end-to-end test and a real cancellation-during-
connector-read test.

## Latency (`orca/connectors/latency_bench.py`)

Framework overhead only (excludes real DocStore query time, reported
separately and honestly as such):

| Operation | Mean | p95 |
|---|---|---|
| connector_lookup | <0.01ms | <0.01ms |
| policy_decision | <0.01ms | <0.01ms |
| is_routable_check | <0.01ms | <0.01ms |
| audit_event_creation | ~0.01ms | ~0.01ms |
| federated_search_planning (empty read_fns) | ~0.01ms | ~0.01ms |
| document_store_read (includes real DocStore query -- NOT framework overhead) | ~70ms | ~82ms |

The framework's own overhead is sub-millisecond in every case; the
~70ms figure is dominated entirely by the real ChromaDB/embedding query
inside DocStore, disclosed as such rather than mislabeled as connector
framework cost.
