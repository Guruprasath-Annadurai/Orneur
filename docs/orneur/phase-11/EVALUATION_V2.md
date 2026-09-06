# Phase 11.1 — Closure Evaluation

## Original Phase 11 harness (preserved, independently green)

`orca/simulation/eval_harness.py`: 23/23 (100%), unchanged.

## Closure harness

`orca/simulation/eval_harness_v2.py`: 21/21 (100%) — two-action
projection chain, dependency-blocked simulation, multi-action aggregate
blast radius/reversibility, branch success/failure outcomes, branch
maximum under an adversarial plan, branch state isolation, branch
budget sharing, fresh-external-assumption Truth trigger, Truth
SUFFICIENT/CONFLICTED/INSUFFICIENT verdict impact, cancel-between-
actions, partial-result-on-cancel, no-orphan-task, projected-action-
influences-next, real-WorldState-unchanged, elevated-multi-action-
preview-consumes-no-lease, real-action-revalidates-lease-independently,
plan-RealityDiff match/mismatch-halts.

Run: `.venv/bin/python -m orca.simulation.eval_harness_v2`

## Pytest suite

29 new tests across 3 files:

| File | Tests |
|---|---|
| `tests/test_simulation_closure.py` | 26 |
| `tests/test_simulation_e2e.py` (2 new tests added) | +2 |
| `tests/test_simulation_fast_path.py` (1 new test added) | +1 |

Combined simulation-specific test count: 50 (was 22 after Phase 11 —
Phase 11.1 nearly triples coverage).

## Latency (extended)

| Operation | Mean | p95 |
|---|---|---|
| multi_action_plan_orchestration (2 actions) | ~1.4ms | ~1.6ms |
| branch_setup_and_aggregation | ~1.4ms | ~1.6ms |
| truth_trigger_policy_decision | ~0.0005ms | ~0.0007ms |
| plan_reality_diff | ~0.03ms | ~0.04ms |
| async_scheduling_plus_cancellation_cleanup | ~0.82ms | ~0.96ms |

The multi-action/branch entries are dominated by real disk I/O (the
same cost the single-action `filesystem_sandbox_simulation_full`
benchmark already measures at ~1.1-1.5ms) — framework orchestration
overhead on top of that I/O remains sub-millisecond, confirmed by
comparing against the pure-framework entries (requirement decision,
execution gate, etc., all still <0.001ms as in Phase 11).

## Fast path (extended)

`orca/simulation/chamber.py` (single-action) never imports
`orca.simulation.plan_chamber` or `orca.simulation.branching` — a
single-action static/read-only simulation pays zero multi-plan/branch
overhead, verified by AST inspection.

## Phase 11.2 — Final qualification (kept separate, not merged)

Both harnesses above are re-confirmed independently green after Phase
11.2's changes, unmerged into a single percentage:

- `orca/simulation/eval_harness.py`: **23/23 (100%)**, unchanged.
- `orca/simulation/eval_harness_v2.py`: **21/21 (100%)**, unchanged.

Phase 11.2 added no new eval-harness scenarios — the 6 qualification
requirements (active dual-branch cancellation, branch cancellation
budget reconciliation, Truth request cancellation while in-flight,
Truth cancellation preventing VERIFIED/PASS, cancellation/completion
race semantics, zero orphan tasks) are covered by a dedicated pytest
file instead, `tests/test_simulation_qualification_11_2.py` (8 tests,
all real asyncio synchronization — `asyncio.Event`/`asyncio.TaskGroup`
— not sequential calls dressed up as concurrent). This file is now
part of the authoritative security suite inventory
(`docs/orneur/phase-9/security_suite_files.txt`, 74 files).

## Phase 11.2 — Real Gateway-layer bug found and fixed

While investigating two live-suite failures previously mislabeled
"environmental," root-cause work traced both to the same underlying
defect: `OllamaRuntime.generate()` unconditionally converted ANY
`asyncio.CancelledError` into a domain `RequestCancelledError`, which
defeats `asyncio.wait_for()`'s ability to convert its OWN timeout
expiry into `TimeoutError` at every layer that wraps a real generate()
call with a deadline (`Gateway.generate()`'s `total_request_timeout_s`,
`CognitiveCourt.run()`'s `COURT_DEADLINE_S`, `TruthFabric`'s several
`*_TIMEOUT_S` values) — under real sustained load, a deadline that
should have produced a clean, already-handled timeout instead escaped
as an unhandled exception. Fixed at the true source
(`orca/gateway/ollama_runtime.py`): only requests explicitly cancelled
via `runtime.cancel(request_id)` now raise `RequestCancelledError`; any
other `CancelledError` propagates natively so every enclosing
`wait_for()` continues to work as designed. See
`docs/orneur/phase-11/LIVE_RUNTIME_QUALIFICATION.md` for the full
evidence trail and `docs/orneur/phase-11/PHASE_11_FINAL_CLOSURE.md`
for the closure summary.
