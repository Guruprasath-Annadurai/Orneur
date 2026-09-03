# Phase 13 — Attack Surface Map

This is a map, not a duplicate of subsystem documentation already written
in Phases 1-12.1 — each row points at the real code and the real security
tests that already exist for it, plus what this phase added.

| Surface | Real entry point(s) | Existing security coverage | Phase 13 additions |
|---|---|---|---|
| API / auth / entitlement | `orca/serve/api.py`, `orca/auth/store.py` | `test_auth_store.py`, `test_auth_privacy.py`, `test_org_store.py`, `test_account_delete.py` | Audited, not newly tested — see Known Limitations. |
| Cognitive Kernel | `orca/cognitive/` | Covered indirectly via API cutover tests (`test_api_production_cutover.py`, deterministic portion) | None — out of scope this pass. |
| Gateway / model runtime | `orca/gateway/gateway.py`, `ollama_runtime.py`, `frontier_runtime.py` | `test_gateway_chaos.py`, `test_gateway_circuit_breaker.py`, `test_gateway_test_isolation.py` | **New**: `test_frontier_runtime_cancellation.py` — the explicitly-flagged Phase 11.2-analogous risk, investigated and disproved with real evidence. |
| Truth Fabric / RAG | `orca/truth/` | `test_truth_fetch_security.py`, `test_truth_safe_fetch_cutover.py`, `test_truth_evidence_provenance_graph.py`, `test_truth_corrective_contradiction_counter_evidence.py` | Audited; source-independence/citation-confusion campaigns not newly executed this pass (disclosed limitation). |
| Memory Continuum | `orca/memory/` | `test_memory_security.py`, `test_memory_authority_security.py`, `test_memory_deletion_integration.py`, `test_memory_retrieval_consolidation_firewall.py`, `test_memory_reflex_*.py` | None new — coverage already substantial. |
| Cognitive Court / Model Society | `orca/deliberation/`, `orca/society/` | `test_deliberation_security.py`, `test_society_authority_security.py`, `test_society_security.py` | **New**: behavioral (not just structural) cross-layer test proving a Court ACCEPT verdict built from injected content cannot reach Godmode issuance. |
| AgentRuntime / ToolRegistry | `orca/agent/` | `test_agent_security.py`, `test_agent_plan_security.py`, `test_agent_adversarial_phrases.py`, `test_agent_secret_and_trace_security.py`, `test_agent_cancellation.py`, `test_agent_delegation.py`, `test_agent_subagent_cancellation.py` | **New**: `test_redteam_cross_layer_chains.py`'s 3-layer connector→agent→capability-enforcement test. |
| Filesystem / shell / process | `orca/tools/`, `orca/mcp/fs_server.py` | `test_tools_file_sandbox.py`, `test_code_sandbox_safety.py`, `test_run_shell_sandbox.py`, `test_mcp_fs_server_sandbox.py` | None new — PROCESS_EXECUTION Godmode remains disabled (not enabled to test, per spec §82). |
| Network / SSRF | `orca/truth/fetch.py`, `orca/tools/` web tools | `test_web_ssrf_guard.py`, `test_web_ingest.py` | None new. |
| Connectors | `orca/connectors/` | `test_connector_security.py`, `test_connector_tenant_isolation.py`, `test_connector_authority_regressions.py`, `test_connector_rate_limit_and_budget.py`, `test_connector_lifecycle_audit.py` | Reused in the new cross-layer chain tests. |
| Godmode | `orca/godmode/` | `test_godmode_security.py`, `test_godmode_boundaries.py`, `test_godmode_exact_argument_binding.py`, `test_godmode_concurrency_and_e2e.py` | Reused in the new cross-layer chain test's boundary assertion. |
| Simulation Chamber | `orca/simulation/` | `test_simulation_security.py`, `test_simulation_qualification_11_2.py` | None new — result forgery/sandbox escape/staleness/Godmode race already covered. |
| Learning pipeline / registries | `orca/learning/`, `orca/registry/` | `test_learning_phase12.py`, `test_learning_registry_isolation.py`, `test_learning_training_experiment.py` | None new this phase — Phase 12/12.1 already covered curriculum poisoning, tenant leak, holdout, checksum, self-approval. |

## Trust-boundary detail

See [`TRUST_BOUNDARIES.md`](TRUST_BOUNDARIES.md) for the per-boundary
trusted/untrusted field breakdown.
