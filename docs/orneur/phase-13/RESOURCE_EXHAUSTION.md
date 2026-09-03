# Phase 13.1 — Resource Exhaustion / Structured-Input Bombs

12 new attacks executed against real code (`tests/test_redteam_resource_exhaustion.py`).

| ID | Attack | Target | Status | Severity |
|---|---|---|---|---|
| RES-01a | Godmode argument deep-nesting (depth 500) | `orca.godmode.canonical.hash_arguments` | **REAL_VULNERABILITY — FOUND AND FIXED** (was: uncaught `RecursionError`) | MEDIUM |
| RES-01b | Regression: shallow realistic arguments unaffected | same | BLOCKED_AS_EXPECTED | — |
| RES-02a | AgentPlan oversized task count | `orca.agent.planner._validate_and_build_plan` | BLOCKED_AS_EXPECTED | — |
| RES-02b | AgentPlan oversized action count | same | BLOCKED_AS_EXPECTED | — |
| RES-03a | AgentPlan oversized per-task dependency list | same | BLOCKED_AS_EXPECTED | — |
| RES-03b | JSON bomb hidden inside plan action arguments | same | BLOCKED_AS_EXPECTED (completes without crash) | — |
| RES-04 | Delegation depth overflow | `orca.agent.delegation.build_child_runtime` | BLOCKED_AS_EXPECTED (`DelegationDepthExceededError`) | — |
| RES-05 | Truth Fabric retrieval-budget exhaustion (max_retrieval_calls=0) | `orca.truth.truth_fabric.TruthFabric.assess_evidence` | BLOCKED_AS_EXPECTED (`TruthBudgetExhaustedError`) | — |
| RES-06 | Simulation action-count overflow | `orca.simulation.plan_chamber.simulate_plan` | BLOCKED_AS_EXPECTED | — |
| RES-07 | Simulation branch-count overflow | `orca.simulation.branching.run_bounded_branches` | BLOCKED_AS_EXPECTED | — |
| RES-08 | 200-event near-duplicate FailureEvent storm | `orca.learning.pipeline.run_pipeline` | BLOCKED_AS_EXPECTED (deduped to 1, <5s) | — |
| RES-09 | Regex/parser DoS timing (1KB→100KB adversarial strings) | `orca.connectors.security.redact_secrets` | BLOCKED_AS_EXPECTED (linear scaling, <2s on 100KB) | — |

## The real finding (RES-01a)

See `docs/orneur/phase-13/FINDINGS.md`'s full writeup and
`RAG_DEEP_RED_TEAM.md`'s neighboring RAG-02 finding for the sibling case
in Truth Fabric. `orca.godmode.canonical._canonicalize_value()` recursed
with no depth guard; a payload nested 500 levels deep (plausible, not an
extreme value) raised an uncaught `RecursionError` directly out of
`issue_lease()`/`resolve_lease()`/`resolve_and_consume_lease()` — the
real Godmode authorization entry points. Fixed with an explicit depth
counter (`_MAX_CANONICALIZATION_DEPTH = 64`) raising a typed,
catchable `ArgumentTooDeeplyNestedError`.

## Regex/parser DoS methodology (spec §26-27)

Measured, not assumed from visual inspection alone: `redact_secrets()`
was timed against 1KB, 10KB, and 100KB adversarial strings (padding plus
an embedded fake credential). A catastrophic (exponential/quadratic)
pattern would show wildly disproportionate growth; observed timing
stayed well within a generous 5000x bound for a 100x size increase, and
under 2 seconds absolute on the 100KB case — consistent with the
patterns' straightforward, non-nested-quantifier structure.
