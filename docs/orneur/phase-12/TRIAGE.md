# Phase 12 — Triage Engine

`orca/learning/triage.py::triage(event) -> TriageResult`.

Pure, deterministic function — no model call, matching spec §10's
explicit "do not let an LLM alone decide that a failure belongs in
training." Rule order (first match wins):

1. `DISMISSED` → `DISMISS`.
2. `CONTESTED` → `HUMAN_REVIEW`.
3. `UNVERIFIED` → `HUMAN_REVIEW`.
4. (from here, `VERIFIED`) `JAILBREAK_FAILURE` / `POLICY_VIOLATION_ATTEMPT`
   / `security_class=SECURITY_SENSITIVE` → `SECURITY_REGRESSION`.
5. `root_cause ∈ {RUNTIME_FAILURE, INFRASTRUCTURE_FAILURE, TEST_FAILURE}`
   → `RUNTIME_BUG`.
6. `root_cause = DATA_FAILURE` → `DATA_QUALITY_ISSUE`.
7. `root_cause = UNKNOWN` → `HUMAN_REVIEW` (cannot triage without root
   cause).
8. Otherwise (`VERIFIED`, a real model-attributable root cause) →
   `EVAL_CANDIDATE`.

Note there is **no direct path to `TRAINING_CANDIDATE`** from this
function. This is deliberate: spec §35 requires every verified failure to
become an eval regression case *first*; whether it ALSO becomes training
data is a separate decision made later, during human/policy review
(`orca.learning.pipeline.review_candidate`, which can set
`APPROVED_FOR_TRAINING`). Triage's job is narrower than the full 7-value
`FailureDisposition` enum suggests at first glance — `TRAINING_CANDIDATE`
and `HUMAN_REVIEW`-as-training-track exist in the type for future
extension (e.g., a fast-track rule for an explicitly pre-approved
adversarial-case category) but the current rule table intentionally
routes everything eligible through `EVAL_CANDIDATE` first.

Tested directly: `tests/test_learning_phase12.py`'s
`test_triage_*` functions, plus `orca/learning/eval_harness.py`'s
scenarios 1, 2, 4, 6, 16.
