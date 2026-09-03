# Phase 11 — Reality Reconciliation

`orca/simulation/reality_diff.py::reconcile()` — "one of the most
important Phase-11 mechanisms" per the spec's own framing: the only
place a simulation's honesty is checked against what actually happened.

## Method

Deterministic, string-containment-based comparison against a REAL
post-execution `orca.agent.contracts.Observation` — deliberately simple
and auditable rather than a model "judging" the match:

- `observation.status == "ERROR"` -> `MISSING_EXPECTED_EFFECT` (or
  `UNEXPECTED_EFFECT` if nothing was even predicted), severity `HIGH`.
- `observation.status == "CANCELLED"` -> `OUTCOME_UNKNOWN`, true outcome
  genuinely unknown.
- Every predicted resource mentioned in `observation.facts` -> `MATCHED`.
- Some but not all -> `PARTIAL_MATCH`.
- None -> `MISSING_EXPECTED_EFFECT`, severity `HIGH`.

## Failure candidates, never automatic memory (spec §61-62)

`failure_candidate_from_diff()` emits a `FailureCandidateRecord`
(`simulation_failure_candidate` kind) for any non-`MATCHED` diff — and
ONLY that. It never calls anything in `orca.memory` — normal Memory
Continuum governance (MemoryArbiter, unchanged) remains the sole path to
durable memory, and Phase 12's training-data loop (explicitly out of
scope for Phase 11) is never touched by this function at all.

## Verified

`tests/test_simulation_e2e.py`'s real end-to-end test confirms a real
filesystem write's actual `Observation` reconciles to `MATCHED` against
its own real predicted effect. `orca/simulation/eval_harness.py`
scenarios 21-22 cover both the matched and mismatched cases, confirming
a mismatch produces a `FailureCandidateRecord` while a match produces
`None`.
