# Cognitive Budget Market — Foundation (Phase 6)

`orca/deliberation/budget_market.py::allocate_budget()`. **Not** an
economic-token simulation (spec §32) — a deterministic, testable
allocator over seven dimensions (retrieval, reasoning, falsification,
verification, counter_evidence, simulation, agents), always summing to
1.0.

## Rules (spec §33), each independently tested

| Signal | Effect |
|---|---|
| LOW uncertainty (< 0.3) | shifts weight from retrieval/falsification → reasoning (more budget to answer generation) |
| Evidence conflict present | shifts weight from reasoning/agents → retrieval/falsification |
| HIGH/CRITICAL risk | shifts weight from reasoning/agents/simulation → verification |
| HIGH/DEEP complexity with real uncertainty | shifts a smaller amount from reasoning → falsification/simulation |
| LOW remaining latency (< 5000ms) | shifts weight from falsification/simulation/counter_evidence → reasoning (the most skippable work is squeezed out first under time pressure) |

Each rule is applied as a bounded weight transfer (`_shift()`), then the
whole distribution is renormalized to sum to exactly 1.0 — proven for
every input combination:
`tests/test_deliberation_budget_market.py::test_allocation_always_sums_to_one`.

## What this is NOT yet wired into

This is a **foundation** — `allocate_budget()` is not yet called from
`CognitiveKernel`/`CognitiveCourt` to actually gate how many rounds/
calls each dimension gets in this phase. `CognitiveCourt` today spends a
fixed, small, hard-bounded amount (exactly 2 model calls per round,
`MAX_ROUNDS_COURT=3` rounds max) regardless of the allocator's output.
Wiring the allocator's percentages into actual per-dimension spending
caps is real, valuable follow-up work for a later phase — this phase
delivers the allocation *policy* itself, deterministic and tested, per
spec §33's explicit "deterministic/testable initially" bar, not the
full closed-loop enforcement.
