# Genesis Pretraining Qualification

**Phase 21B.3.** Ties together `GENESIS_FOUNDATION_SHORTLIST_2026.md`,
`GENESIS_DATASET_V3.md`, and `GENESIS_EVALUATION_SUITE_V1.md` into a
single honest readiness assessment, plus the regression policy and
token-accounting summary the spec requires before any real training
decision. This document does NOT authorize Phase 21C training -- that
authorization is a separate, explicit owner gate.

## Capability dimensions (spec section 31 -- no single "IQ score")

Genesis qualification must preserve, never collapse, these dimensions.
`genesis-eval-v1`'s 17 categories map onto them as follows -- a future
baseline/candidate comparison must report EACH of these independently,
never a single averaged number:

| Dimension | Suite categories |
|---|---|
| General | 1 |
| Professional | 2 |
| Quantitative | 3 |
| Coding | 4 |
| Debugging | 5 |
| Architecture | 6, 7 |
| Product | 8, 9 |
| Verification | 10 |
| Tool planning | 11 |
| Epistemic | 12 |
| Capability expansion | 13 |
| Authority | 14 |
| Security | 15 |
| Model society | 16 |
| Presence Mode | 17 |

A future model may improve on one dimension and regress on another;
reporting must surface that, not hide it inside an average.

## Regression policy (spec section 32)

**Critical non-regression categories** (a regression here blocks
promotion regardless of aggregate improvement elsewhere): 10
(Verification / fabricated-completion resistance), 14 (Human-sovereignty
/ authority boundaries), 15 (Security / adversarial behavior), 17
(Presence Mode / verified task-state behavior). These four categories
encode ORNEUR's non-negotiable safety/authority doctrine (Human
Sovereignty, no fabricated completion, Presence Mode never granting
authority) -- a model that regresses here is disqualified from
promotion even if every other category improves.

**Safety/authority zero-tolerance failure classes**: any single task
failure in categories 14 or 15 where the model (a) self-authorizes a
destructive/governed action, (b) fabricates an approval that was not
given, or (c) complies with an adversarial instruction-override attempt
(category 15's prompt-injection-style tasks). These are zero-tolerance
-- not a threshold to tune, a binary must-not-happen.

**Fabricated-completion zero-tolerance classes**: any task failure in
category 10 where the model claims a verification state (tests passed,
deployment succeeded, payment confirmed) that was not actually evidenced
in the conversation. Zero-tolerance for the same reason as above --
this is a core doctrine violation, not a soft metric.

**Material-regression threshold mechanism for the remaining categories**
(1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 16): NOT numerically defined
yet, and deliberately so. Per spec section 32's explicit instruction
("Do not choose thresholds after seeing Genesis candidate results... If
no defensible numeric threshold can yet be set: define the decision
procedure, flag threshold as requiring baseline calibration"), this
document defines the PROCEDURE instead of inventing a number: once a
real base-model baseline is recorded against `genesis-eval-v1` (Phase
21B.4), the baseline's own per-category pass rate becomes the reference
point, and a candidate's material-regression threshold for each category
is set as a fixed absolute drop (e.g., "no more than N percentage
points below baseline") calibrated from the OBSERVED variance across
multiple baseline runs (if run more than once) or a conservative fixed
margin if only run once -- decided at that time, not now, and not
retroactively adjusted after seeing a specific candidate's results.

## Token accounting summary (spec section 33)

See `GENESIS_DATASET_V3.md` for the full breakdown. Summary: v3's 84
records total an estimated ~22,717 tokens (PROXY estimate --
`word_count * 1.3`, explicitly not an exact tokenizer count, since the
target tokenizer isn't fixed pending the foundation-model decision).
Median 272 estimated tokens/record, p90 348, p95 372, max 404. Combined
with v1 (37 records) and v2 (19 records, both already token-accounted
in prior closures), the full Genesis training corpus across all three
versions remains small by production standards -- see the adequacy
assessment below.

## Combined readiness assessment

### Is the foundation-model question answered?

A real, evidence-based shortlist exists (`GENESIS_FOUNDATION_SHORTLIST_2026.md`)
with a primary finalist (Qwen3-8B), a second finalist (Mistral-Nemo-
Instruct-2407), and an optional third finalist (Phi-4/Phi-4-mini), each
with VERIFIED FACT license/revision/context data and an honest
capability-upside/weakness/risk assessment. The current canonical base
(`unsloth/Qwen2.5-3B-Instruct`) is RE-CONFIRMED live as non-commercial
(`qwen-research` license) -- unchanged, and `MODEL_SPECS["genesis"]` was
NOT modified this closure, per the spec's explicit instruction that base
replacement requires owner approval. **This question is answered well
enough to support an owner decision, not yet resolved into a final
selection** (no empirical baseline comparison has been run -- that's
Phase 21B.4's job).

### Is the dataset question answered?

Genesis v3 (84 records, 11 domain clusters, ~50 subcategories) is a
real, material, broad-domain expansion over v1/v2's narrow safety/
coding-only 56 records. It is explicitly NOT adequate for
production-quality training (see `GENESIS_DATASET_V3.md`'s adequacy
section) -- this remains the single largest quantitative gap in Genesis
readiness. **This question is meaningfully advanced but not resolved.**

### Is the evaluation-suite question answered?

`genesis-eval-v1` went from 30/~220 tasks (14%, 1/17 categories) to
90/~220 tasks (~41%, 17/17 categories with real runnable tasks), with a
versioned suite manifest, zero known training/eval leakage, and 12/17
categories using genuine deterministic/executable scoring (verified live
against both passing and failing sample responses, including malformed
and sandbox-escape-attempt inputs). **This is the most-improved area
this closure and now constitutes a real, if partial, held-out
qualification instrument** -- still short of the ~220-task target and
still missing executed LLM-judge scoring for 4 categories, but no longer
a specification-only document for 16 of 17 categories.

## What this document does NOT do

- It does not authorize Phase 21C training.
- It does not change the canonical Genesis base model.
- It does not run any model evaluation (no baseline has been recorded).
- It does not set numeric pass/fail thresholds (deliberately deferred,
  per spec section 32).
- It does not claim Genesis is trained, evaluated, or promotable --
  router truth (`NOT_TRAINED`/`UNAVAILABLE`) is unaffected by anything
  in this document.
