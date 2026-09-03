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

## Phase 11.1 — Plan-level reconciliation

`orca/simulation/reality_diff.py::reconcile_plan()` extends the
single-action `reconcile()` to a whole plan: `PlanRealityDiff` holds one
`RealityDiff` PER ACTION (never a single flattened diff that hides which
specific action diverged) plus a deterministic `aggregate_status` (worst
severity across all per-action diffs) and a `remaining_actions_halted`
flag.

`remaining_actions_halted` is `True` whenever the aggregate status is
`MISSING_EXPECTED_EFFECT` or `UNEXPECTED_EFFECT` (spec §40: a plan
should not blindly continue after a material divergence) — a caller
observing this flag is expected to stop, replan, re-simulate, or
escalate to Court, never silently execute the remaining actions against
a plan that has already proven stale in practice.

Verified directly: two actions where the first matches and the second
diverges correctly aggregate to `MISSING_EXPECTED_EFFECT` with
`remaining_actions_halted=True`, while the first action's own correct
`MATCHED` status is preserved per-action (not lost in the aggregation).
