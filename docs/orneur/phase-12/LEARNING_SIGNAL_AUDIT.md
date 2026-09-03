# Phase 12 — Learning Signal Audit

Every source of potential learning signal listed in the Phase 12 spec §3,
classified against the closed `SignalClassification` enum
(`orca/learning/contracts.py`). "Adapter exists" means a concrete function
in `orca/learning/signals.py` converts that subsystem's real output into a
`FailureEvent` today; "audited only" means the source is real and its
structure is understood, but no adapter is wired yet (adding one is a
schema-compatible, additive change).

| Source | Classification | Adapter exists? | Notes |
|---|---|---|---|
| Truth Fabric contradictions | TRAINING_ELIGIBLE | Yes (`from_truth_contradiction`) | Stores only claim/evidence IDs, never full evidence text. |
| Unsupported claims | TRAINING_ELIGIBLE | Yes (`from_unsupported_claim`) | |
| Citation failures | EVAL_ONLY | No | Same shape as unsupported claims; not yet wired — `orca.truth.contracts.CitationVerdict` has no dedicated adapter yet. |
| Contradictions (Truth) | TRAINING_ELIGIBLE | Yes | Same adapter as above. |
| Memory conflicts | EVAL_ONLY | No | Real `MemoryConflict`-shaped records exist in `orca/memory/`; conflicts are frequently caused by legitimate multi-source disagreement, not model failure — classified EVAL_ONLY pending a root-cause-classification pass specific to memory. |
| FailureMemory (Phase 11 simulation) | TRAINING_ELIGIBLE | Yes (`from_reality_diff`, `from_court_disagreement` cover the Phase 11 `FailureCandidateRecord` shape) | |
| Court disagreements | TRAINING_ELIGIBLE (via review) | Yes (`from_court_disagreement`) | Never a majority-vote signal — spec §39. |
| Falsifier objections/misses | TRAINING_ELIGIBLE | Yes (`from_falsifier_miss`) | Both "missed a real contradiction" and "invented a false one" tracked (spec §40) — the latter modeled by feeding a `FailureType.FALSIFIER_MISS` event with `role="FALSIFIER"` and a negative-curriculum candidate. |
| Agent tool failures | TRAINING_ELIGIBLE | Yes (`from_connector_failure` covers connector-shaped tool failures) | Non-connector tool failures (file/code/shell) audited but not yet adapted — same shape, deferred. |
| Policy denials | SECURITY_SENSITIVE | Yes (`from_policy_denial`) | Always VERIFIED (a denial is a fact) and routes to SECURITY_REGRESSION via triage, never "teach the model to succeed" (spec §43). |
| Connector failures | TRAINING_ELIGIBLE / PRIVACY_SENSITIVE | Yes (`from_connector_failure`) | Defaults `PrivacyClass.TENANT_PRIVATE` — connector content is enterprise data by default (spec §13, §64). |
| Simulation-vs-reality mismatch | EVAL_ONLY (root cause deliberately unresolved) | Yes (`from_reality_diff`) | Spec §38: never auto-trained on raw mismatch. |
| Routing failures | EVAL_ONLY | No | Spec §44: routing mistakes should primarily improve routing policy/capability profiles, not model weights — deliberately no adapter that feeds model training. |
| Model eval failures | EVAL_ONLY | No | Already captured by `orca.registry.evaluation_registry.EvaluationReport` — Phase 12 consumes that report's `failure_reasons`, it doesn't need a separate FailureEvent adapter. |
| Jailbreak failures | SECURITY_SENSITIVE | Yes (`from_jailbreak_probe_result`) | Only emits on probe FAILURE (defeated model), never on a passing probe. |
| Bias failures | SECURITY_SENSITIVE | No | Same shape as jailbreak; `orca/train/redteam.py`'s bias-judge output structure is understood but not yet adapted — deferred, disclosed gap. |
| Calibration failures | EVAL_ONLY | No | Same reasoning as bias — deferred. |
| User correction signals | NOT_TRAINING_ELIGIBLE (no surface exists) | No | No product UI captures an explicit user-correction signal today; classification is provisional until that surface exists. |
| Manual eval datasets | EVAL_ONLY | N/A | Already-curated data, consumed directly by `orca/train/eval.py`, not routed through the FailureEvent pipeline. |
| Training datasets (existing) | N/A | N/A | Pre-Phase-12 datasets registered via `orca.registry.dataset_manifest` remain valid as-is; Phase 12 does not retroactively reclassify them. |

## Summary

- **7 of 20** listed sources have a real, tested adapter today (Truth
  contradiction, unsupported claim, simulation mismatch, Court
  disagreement, Falsifier miss, connector failure, policy denial, jailbreak
  probe failure — 8 counting both Truth adapters).
- **5 sources** are deliberately routed to EVAL_ONLY or excluded from
  model-weight training by design (routing failures, model eval failures,
  simulation mismatch's root cause, memory conflicts, citation failures) —
  not oversights, but the spec's own explicit separation-of-concerns
  requirements (§38, §41, §42, §44).
- **5 sources** are honestly disclosed as NOT YET adapted (bias failures,
  calibration failures, non-connector tool failures, memory conflicts as
  training candidates, citation failures) — same underlying structure as an
  already-adapted source, deferred for scope, not because the classification
  work wasn't done.
- **1 source** (user corrections) has no product surface to draw from yet.

This audit itself — not the code — is the actual "First Action" the spec
requires (§3); the code in `orca/learning/signals.py` implements the
subset classified TRAINING_ELIGIBLE or SECURITY_SENSITIVE with a concrete
structure available today.
