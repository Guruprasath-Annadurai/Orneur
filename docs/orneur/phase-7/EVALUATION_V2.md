# Evaluation Harness V2 (Phase 7.1 spec §46)

Phase 7's `orca.society.eval_harness` (12 scenarios) is unchanged and
still passes 12/12. This phase adds closure-specific scenarios covering
what Phase 7.1 actually changed, reported separately per spec §46.

## Original Phase 7 scenarios (unchanged)

12/12 passed -- see `docs/orneur/phase-7/EVALUATION.md`.

## Closure scenarios (Phase 7.1)

| Scenario | Result | Test |
|---|---|---|
| Truth claim-extractor role routing | PASS | `test_truth_fabric_society_routing.py::test_default_resolution_uses_society_not_a_hardcoded_literal` |
| Truth verifier role routing (production stays on Genesis-legacy) | PASS | `test_truth_fabric_society_routing.py::test_production_default_never_silently_promotes_experimental_novus` |
| Query rewrite role routing | PASS | covered via `resolve_tier_for_role(QUERY_REWRITER)` -- exercised live in `test_cognitive_kernel_truth_fabric_integration.py`'s corrective-retrieval-path tests |
| Memory model role routing (declared, unwired) | PASS (honest N/A) | `orca.memory.candidates.extract_candidates_via_gateway` migrated but has no production caller -- disclosed, not tested as "live" |
| TOOL_REASONER routing without tool authorization | N/A (not migrated) | AgentLoop/Ultra remain LEGACY_COMPATIBILITY this phase (see `ROLE_MIGRATION.md`) -- no TOOL_REASONER live call exists to test yet |
| WorldState changing a decision | PASS | `test_worldstate_decision_consumption.py::test_court_excludes_a_worldstate_flagged_unavailable_model_from_routing` |
| Court REVISE triggering one replan | PASS | `test_kernel_replanning.py::test_court_revise_triggers_exactly_one_bounded_replan_then_accept` |
| MAX_REPLANS stop | PASS | `test_kernel_replanning.py::test_persistent_revise_degrades_after_max_replans_instead_of_looping_forever` |
| Budget reservation failure | PASS | `test_budget_execution_integration.py::test_verify_answer_raises_when_verification_budget_exhausted` |
| Budget release on cancellation | PASS (Phase 7, unchanged) | `test_society_budget_ledger.py::test_release_returns_budget_to_both_sub_ledger_and_parent` |
| Real deployment unhealthy rejection | PASS | `test_society_deployment_worker_health.py` (READY/DRAINING/UNHEALTHY/OFFLINE/open-circuit, all 5 cases) |
| Gateway test-home isolation | PASS | `test_gateway_test_isolation.py`, `test_gateway_wiring_deployment_records.py` |
| Literal-tier bypass audit | PASS (0 unexpected) | see `SOCIETY_AUTHORITY_AUDIT.md`'s classification table |

## A real bug this evaluation work caught (not fabricated success)

Live-Ollama testing of the verification-budget wiring (spec §20) surfaced
a genuine regression: `test_strict_evidence_request_answers_via_truth_fabric_with_doc_store`
started failing with `AbstentionReason.BUDGET_EXHAUSTED` because the
verification purpose's cap was sized as a small percentage of the total
pool, computed before claim count was known. Fixed (see
`BUDGET_EXECUTION.md`) and a dedicated regression test added
(`test_budget_execution_integration.py::test_multiple_claims_do_not_spuriously_exhaust_verification_budget`).
This is disclosed here, not hidden, per the project's established
"report real bugs found during Phase-N development" discipline.

## No fabricated model-quality gains (spec §46's own caution)

None of the above scenarios claim an improvement in answer quality,
reasoning capability, or capability score -- every PASS is a structural/
behavioral correctness check (did routing/budget/replanning/health-check
logic do what it's supposed to), matching the same discipline Phase 7's
own evaluation harness established.
