# Phase 12 — Curriculum Candidates

`orca/learning/contracts.py::CurriculumCandidate` — spec §11.

## Fields

`candidate_id`, `failure_ids`, `task_type`, `target_role`,
`target_model_family`, `input_summary`, `expected_behavior`,
`negative_behavior`, `evidence_refs`, `difficulty`, `privacy_class`,
`security_class`, `training_destination`, `source_lineage`,
`dedupe_fingerprint`, `review_state`, plus synthetic-data metadata
(`is_synthetic`, `synthetic_generator_model`,
`synthetic_generator_checkpoint`, `synthetic_generation_ref`,
`synthetic_verification_state`).

`input_summary` is exactly that — a summary, never a raw dump (spec §12).
`orca.learning.pipeline.make_candidate_from_event` never copies a full
transcript; it takes caller-supplied `input_summary`/`expected_behavior`
strings the caller derived from the owning subsystem's real record.

## Role targeting (spec §19)

`target_role: ModelSocietyRole | None` — `QUERY_REWRITER`,
`CLAIM_EXTRACTOR`, `VERIFIER`, `CONSTRUCTOR`, `FALSIFIER`,
`TOOL_REASONER`. `None` is a valid, common value — not every failure maps
to a role (e.g. a simulation mismatch destined for planning/risk
calibration curriculum, not a specific Model Society role).

## Model family targeting (spec §20)

`TargetModelFamily`: `GENESIS | NOVUS | AETERNUM | FAMILY_SHARED`.
Candidates MAY target `AETERNUM` (dataset/role preparation is allowed per
spec §20/§79) — no code path in this phase ever claims an Aeternum
checkpoint exists as a result.

## Review lifecycle (spec §60)

`CandidateReviewState`: `DRAFT → {APPROVED_FOR_EVAL, APPROVED_FOR_TRAINING,
REJECTED, NEEDS_MORE_EVIDENCE, SECURITY_ONLY, TENANT_LOCAL_ONLY}`.
`orca.learning.pipeline.review_candidate()` is the only function that
performs this transition; it constructs a `ReviewQueueEntry` and calls
`apply_review_decision()`, which raises `ModelCannotSelfApprove` if
`reviewer` starts with `"model:"` (spec §69).

## Synthetic data (spec §46-48)

A candidate created synthetically MUST set `is_synthetic=True` plus
generator provenance; `synthetic_verification_state` defaults to
`UNVERIFIED` and must be explicitly set to `VERIFIED` (by a deterministic
check, Truth Fabric, Court, or human review — never the generator
model's own say-so) before it is admissible. Synthetic and observed data
are never mixed without this metadata — every compiled record
(`CurriculumCompiler.compile`) carries these fields through unchanged.

## Difficulty (spec §18)

`orca.learning.curriculum.score_difficulty()` — a disclosed, fixed-weight
formula over 8 real, inspectable factors (reasoning depth, retrieval
depth, tool count, contradiction count, context length, failure
frequency, Court disagreement, confidence mismatch), each capped against
a documented normalization bound. No arbitrary "hard" label.

## Balance (spec §50)

`orca.learning.curriculum.compute_balance()` reports distribution by
role, model family, difficulty band, and security class — used to detect
one failure class dominating a compiled dataset before it is frozen.
