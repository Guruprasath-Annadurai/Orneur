# Phase 10 — Evaluation

## Deterministic eval harness (`orca/godmode/eval_harness.py`)

24/24 scenarios pass (100%), run against a genuinely isolated
`ORNEUR_HOME` (not just pytest's fixture-based isolation) to
independently confirm no leakage: normal denied action, approved narrow
lease, denied-wrong-resource, expired lease, revoked lease, tampered
lease, wrong tenant, correct-tenant-regardless-of-principal, wrong
operation, one-use lease, concurrent-use race, kill switch, nondelegable
lease, delegable subset lease, untrusted-issuer rejection, model-
injection-cannot-issue, connector narrow write, filesystem narrow write,
budget-shared-with-normal-actions, `OUTCOME_UNKNOWN` under elevated
write race, scope-confusion prefix rejection, wildcard rejection,
restart safety, and a full `AgentRuntime` elevation end-to-end run.

Run: `.venv/bin/python -m orca.godmode.eval_harness`

## Pytest suite

57 tests across 4 files (`tests/test_godmode_security.py`,
`tests/test_godmode_concurrency_and_e2e.py`,
`tests/test_godmode_boundaries.py`, `tests/test_godmode_fast_path.py`),
all passing. Includes a real multi-threaded concurrency race (8 threads
against a one-use lease, exactly 1 succeeds) and full connector/
filesystem/AgentRuntime end-to-end flows.

## Latency (`orca/godmode/latency_bench.py`)

Framework overhead only:

| Operation | Mean | p95 |
|---|---|---|
| lease_lookup | ~0.019ms | ~0.020ms |
| integrity_validation | ~0.023ms | ~0.028ms |
| full_resolve (scope+expiry+revocation+tenant+capability) | ~0.031ms | ~0.034ms |
| audit_event_creation | ~0.004ms | ~0.005ms |
| atomic_use_consumption | ~0.098ms | ~0.184ms |

All sub-millisecond. Normal-mode (no elevation attempted) overhead is
zero by construction — `orca.godmode` is never even imported when
`AgentRuntime` is constructed without `tenant_id`/`lease_resolver`,
verified structurally in `test_godmode_fast_path.py` rather than
measured (there is nothing to measure: no code runs).
