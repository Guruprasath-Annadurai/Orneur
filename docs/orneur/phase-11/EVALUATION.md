# Phase 11 — Evaluation

## Deterministic eval harness (`orca/simulation/eval_harness.py`)

23/23 scenarios pass (100%), run against a genuinely isolated
`ORNEUR_HOME`, covering spec §74's full required list: read-only
no-simulation-required, real filesystem write/delete/path-escape/
root-containment, connector preview + `OUTCOME_UNKNOWN_RISK` flagging,
unsupported-connector `INCONCLUSIVE`, tenant-scope-mismatch `BLOCK`,
destructive-effect detection, staleness detection, `WorldState`
projection non-mutation, structural proof simulation never calls
Capability/Policy/Court, `ExecutionGate` `BLOCK`, one-use-lease-not-
consumed-by-preview, lease-revoked/kill-switch-after-simulation denial,
cancellation/budget-exhaustion representation, and `RealityDiff`
match/mismatch with failure-candidate emission.

Run: `.venv/bin/python -m orca.simulation.eval_harness`

## Pytest suite

51 tests across 4 new files:

| File | Tests |
|---|---|
| `tests/test_simulation_security.py` | 14 |
| `tests/test_simulation_fast_path.py` | 6 |
| `tests/test_simulation_e2e.py` | 2 (both required real end-to-end paths) |
| (chamber/contracts/etc. exercised indirectly through the above and the eval harness) | — |

All passing, including the two required real end-to-end tests (spec
§75-76): a full `AgentGoal -> AgentPlan -> Simulation Chamber ->
Execution Gate -> real AgentRuntime execution -> Observation ->
RealityDiff` path in an isolated temp workspace, and a full Godmode
elevation flow (normal denied -> narrow lease approved -> simulation
without consumption -> real elevated execution -> match -> out-of-scope
denial), with `PROCESS_EXECUTION` never enabled.

## Latency (`orca/simulation/latency_bench.py`)

Framework overhead only:

| Operation | Mean | p95 |
|---|---|---|
| requirement_decision | ~0.0004ms | ~0.0005ms |
| provider_capability_lookup | ~0.0001ms | ~0.0001ms |
| state_fingerprint | ~0.018ms | ~0.019ms |
| worldstate_projection | ~0.013ms | ~0.012ms |
| execution_gate | ~0.0003ms | ~0.0004ms |
| reality_diff_reconciliation | ~0.0035ms | ~0.004ms |
| filesystem_sandbox_simulation (full, real disk I/O) | ~0.61ms | ~0.73ms |

Every framework-only step is sub-millisecond; the one real-I/O step
(full filesystem sandbox simulation) is measured and reported
separately, never conflated with pure framework cost.
