# Phase 9.1 — Live / Integration Test Qualification

## Inventory

| File | Marker | Covers | Required for Phase-9 closure? |
|---|---|---|---|
| `test_agent_planner_live.py` | `live_ollama_smoke` | AgentPlanner real-model plan compilation | YES — AgentRuntime authority chain |
| `test_cognitive_kernel_truth_fabric_integration.py` | `live_ollama_smoke` | CognitiveKernel + Truth Fabric real-model integration | YES |
| `test_truth_fabric_integration.py` | `live_ollama_smoke` | Truth Fabric real evidence/verification path | YES |
| `test_truth_claims_verification_contradiction.py` | `live_ollama_smoke` | Truth Fabric claim verification/contradiction | YES |
| `test_deliberation_court_integration.py` | `live_ollama_smoke` | Cognitive Court real-model deliberation | YES |
| `test_deliberation_cancellation.py` | `live_ollama_smoke` | Deliberation Fabric cancellation under a real model call | YES |
| `test_gateway_observability_cutover.py` | `live_ollama_smoke` | Model Society / Gateway real-model observability path | YES |
| `test_api_production_cutover.py` | `live_ollama_smoke` | Production API cutover against a real model | Indirect (API-layer, not connector-fabric-specific) |

No file marks `live_ollama_stress` currently (that marker exists in
`pyproject.toml` but is deliberately excluded from the normal release
suite — sustained-concurrency overload testing, run explicitly, not part
of qualification gating).

## Real (non-live-model) integration coverage

`orca/docs/store.py`'s `DocStore` is a REAL ChromaDB-or-keyword-fallback
vector store — no `live_ollama_smoke` marker is needed to exercise it for
real, because `DocStore._use_embeddings` degrades to a keyword-BM25
fallback when Ollama embeddings are unavailable rather than requiring a
live model; Phase 9's own connector tests
(`tests/test_connector_document_store.py`,
`tests/test_connector_agent_runtime_e2e.py`) already exercise this real
path with real ingested/retrieved content, with no mocking anywhere in
the call chain.

## No real third-party SaaS connector test exists

Per the Phase 9 architecture audit, no authenticated third-party
connector (GitHub/Slack/Drive/Calendar/Ticketing/CRM/Database) exists in
this codebase. Per Phase 9.1 spec §6 and §29, this is NOT a gap to be
closed by fabricating one — DOCUMENT_STORE (REAL_ADAPTER) is the only
family with real backing infrastructure to test live, and it is
exercised for real per above.

## Results

Live-Ollama qualification run (`pytest -m live_ollama_smoke`):
see PHASE_9_FINAL_CLOSURE.md for the exact pass/fail count from the run
executed as part of this qualification pass (test environment: local
Ollama instance; a test auto-skips, never fails, if Ollama is
unreachable, per `docs/orneur/phase-3/TEST_EXECUTION_POLICY.md`).
