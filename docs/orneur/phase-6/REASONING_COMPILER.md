# Reasoning Compiler (Phase 6)

`orca/deliberation/compiler.py::compile_reasoning_plan()`. Pure,
deterministic, synchronous — no I/O, no model call, mirroring
`orca/cognitive/planner.py` and `orca/truth/planner.py`'s own "pure
planning" charter. Measured at 0.007ms p50 (see
[EVALUATION.md](EVALUATION.md)) — cheap enough to run on every
Truth-Fabric-answered request without a fast-path cost concern.

## Inputs / outputs (spec §5)

```python
compile_reasoning_plan(
    objective: str, complexity: ComplexityLevel, risk: RiskLevel,
    evidence_requirement: EvidenceLevel, truth_result=None, memory_recall_result=None,
) -> ReasoningPlan
```

`ReasoningPlan` carries: `goal`, `mode`, `subproblems`,
`requires_hypotheses`, `evidence_needs`, `requires_falsification`,
`requires_counterfactual`, `requires_court`, `max_rounds`,
`max_hypotheses`, `completion_conditions`, `reasons` (a human-readable
audit trail of why each flag was set — never silent).

## Mode selection (spec §6) — never "complexity=HIGH implies Court"

| Signal | Effect |
|---|---|
| Causal language (`why did`, `what caused`, `root cause of`) | `mode = CAUSAL` |
| Counterfactual language (`what if`, `had not occurred`, `would still`) | `mode = COUNTERFACTUAL`, `requires_counterfactual = True` |
| Ambiguity (`could be`, `either...or`, `diagnose`) OR a **DIRECT_CONTRADICTION** in `truth_result.contradictions` | `requires_hypotheses = True`, `mode = MULTI_HYPOTHESIS` (if not already causal/counterfactual) |
| `evidence_requirement == AUDIT_GRADE`, OR `risk in (HIGH, CRITICAL)`, OR a real evidence conflict | `requires_court = True`, `requires_falsification = True`, `mode = COURT_REVIEW`, `max_rounds = 3` |
| `complexity in (HIGH, DEEP)` with `evidence_requirement in (STRICT, SUPPORTED)`, and none of the above | `mode = DELIBERATIVE`, `requires_falsification = True`, `max_rounds = 2` |
| Low complexity, low risk, no ambiguity, no conflict | `mode = DIRECT` |
| Everything else | `mode = ANALYTICAL` |

Court is triggered by exactly three independent signals — evidence
strength/audit requirement, consequence, and a *real* evidence conflict
— checked as an explicit `if` block **before** the complexity-based
`DELIBERATIVE` branch, so complexity alone can never reach it (proven:
`tests/test_deliberation_contracts_hypothesis.py::
test_high_complexity_alone_does_not_force_court`).

## A real bug found and fixed: not every contradiction is a conflict

The first implementation treated ANY non-empty
`truth_result.contradictions` list as an "evidence conflict" — including
`TEMPORALLY_RECONCILABLE` and `SCOPE_DIFFERENCE`, which Truth Fabric's
own `orca/truth/contradiction.py` already classifies as **not** a
standing conflict. This caused a previously-reliable STRICT-evidence
request to start abstaining unnecessarily once Court was wired into the
Kernel (caught live, during integration — see
[PHASE_6_CLOSURE.md](PHASE_6_CLOSURE.md)). Fixed: only a genuine
`DIRECT_CONTRADICTION` counts. Regression-tested:
`tests/test_kernel_court_integration.py::
test_direct_contradiction_triggers_court_but_temporal_reconciliation_does_not`.

## Bounded everything

`MAX_HYPOTHESES = 4`, `MAX_ROUNDS_DEFAULT = 1`, `MAX_ROUNDS_DELIBERATIVE
= 2`, `MAX_ROUNDS_COURT = 3` — no mode ever produces an unbounded round
count, matching the same discipline already established for Truth
Fabric's retrieval planner and Memory Continuum's reflex/consolidation
bounds.
