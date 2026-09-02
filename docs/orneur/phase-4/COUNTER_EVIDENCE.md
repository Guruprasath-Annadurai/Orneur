# Counter-Evidence Hook (Phase 4.1)

**Explicitly not the Epistemic Twin.** No autonomous agent swarm, no
open-ended adversarial research loop, no self-directed "keep looking
until convinced" behavior. `orca/truth/counter_evidence.py::
find_counter_evidence()` is exactly one bounded operation: given a claim
the verifier already judged `SUPPORTED`, issue **one** adversarial search
query (`"evidence against: <claim text>"`) and return whatever comes
back as additional, unfiltered evidence — it does not re-verify the
claim, does not change the claim's verdict, and does not decide anything
on its own.

## When it runs

`TruthFabric.verify_answer(..., run_counter_evidence=True)` — the Kernel
passes `run_counter_evidence=True` only for AUDIT_GRADE requests
(`orca/cognitive/kernel.py::_answer_with_truth_fabric`). It targets the
first claim the verifier found `SUPPORTED` (`ClaimSupportState.SUPPORTED`);
if there is no such claim, it records `NOT_RUN` immediately rather than
searching against an unsupported or unknown claim.

## Budget honesty (spec §17)

```python
class CounterEvidenceStatus(str, Enum):
    RAN = "RAN"
    NOT_RUN = "NOT_RUN"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
```

If `CognitiveBudget`'s `RETRIEVAL_CALLS` dimension is exhausted,
`find_counter_evidence()` returns `BUDGET_EXHAUSTED` — it never silently
skips the check while still labeling the result as if the check had run.
`tests/test_truth_corrective_contradiction_counter_evidence.py::
test_counter_evidence_not_run_without_budget_pretense` proves this with a
zero-capacity budget.

## Wired into the AUDIT_GRADE gate

`_answer_with_truth_fabric` requires `final.counter_evidence.status ==
CounterEvidenceStatus.RAN` (not merely "attempted", not `NOT_RUN`, not
`BUDGET_EXHAUSTED`) as one of the conditions for AUDIT_GRADE success
(spec §16-17, §23) — an AUDIT_GRADE answer whose counter-evidence check
couldn't actually run (budget exhausted, or no supported claim to check)
abstains with `INSUFFICIENT_EVIDENCE` rather than silently succeeding
without ever having looked for disconfirming evidence.

## What this deliberately does not do

- Does not automatically incorporate counter-evidence into the citation
  verdict or claim-support state — it is surfaced on `TruthResult.
  counter_evidence` for observability/manifest purposes (spec §25), not
  fed back into `verify_claim()`'s own judgment in this phase.
- Does not retry, reformulate, or chain further searches if the first
  counter-evidence query comes back empty — one bounded attempt, full
  stop, exactly as the spec's "no autonomous agent swarm" requires.
- Does not run for STRICT (only AUDIT_GRADE) or for any non-Truth-Fabric
  path.
