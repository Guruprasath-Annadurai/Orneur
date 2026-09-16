# Genesis Evaluation Suite v1 — Specification

Phase 21B.1. **This document specifies the suite. It is NOT a fully
built, executable evaluation suite** -- honest scope limitation, stated
upfront rather than discovered later. Only category 1 (below) has a
real, executable implementation (`orca/train/genesis_eval.py`,
pre-existing). Categories 2-16 are specified (task shape, scoring
approach, held-out policy) but not yet implemented as runnable code.
This is the single largest remaining gap before Phase 21C readiness --
see `PHASE21_GENESIS_BUILD_PREPARATION.md`'s blocker list.

## Suite identity

Version: `genesis-eval-v1`. Immutable once any real baseline/candidate
score is recorded against it (mirroring `DatasetManifest`'s freeze
semantics) -- a category's scoring method may not change after a real
comparison has been made against it, or the comparison becomes
meaningless.

## Categories

| # | Category | Task count (target) | Task count (built) | Scoring | Held-out |
|---|---|---|---|---|---|
| 1 | General instruction following / professional / everyday business (Hindi-English) | 30 | **30 (existing `genesis_eval.py`)** | Keyword coverage | Not formally split from training data |
| 2 | Broad professional reasoning | 15+ | 0 | LLM-judge (subjective, flagged) | Not built |
| 3 | Quantitative reasoning | 15+ | 0 | Exact numeric/structured-output match | Not built |
| 4 | Coding (function implementation, bug fixes) | 20+ | 0 | **Executable unit tests** (preferred) | Not built |
| 5 | Debugging | 15+ | 0 | Executable (repro test passes after fix) | Not built |
| 6 | Software architecture | 10+ | 0 | LLM-judge against a rubric | Not built |
| 7 | Multi-file reasoning | 10+ | 0 | Executable (diff correctness) | Not built |
| 8 | Requirements interpretation | 10+ | 0 | LLM-judge (did it ask the right clarifying questions) | Not built |
| 9 | Product-building reasoning | 10+ | 0 | Structured fixture checklist (not full browser benchmark) | Not built |
| 10 | Verification / fabricated-completion resistance | 15+ | 0 | Deterministic string/structure match (`VERIFICATION: UNVERIFIED` pattern present when appropriate) | Not built |
| 11 | Tool planning | 10+ | 0 | Structured-output schema check | Not built |
| 12 | Uncertainty / epistemic behavior | 10+ | 0 | Deterministic pattern match + LLM-judge fallback | Not built |
| 13 | Capability-expansion reflex (ASI protocol) | 10+ | 0 | LLM-judge against the canonical loop's steps | Not built |
| 14 | Human-sovereignty / authority boundaries | 15+ | 0 | Deterministic pattern match (refusal/deferral language present) | Not built |
| 15 | Security / adversarial behavior | 15+ | 0 | Deterministic pattern match + manual review | Not built |
| 16 | Model-society interchange | 10+ | 0 | Structured fixture (correct handoff decision) | Not built |
| 17 | Presence Mode / verified task-state behavior | 10+ | 0 | Deterministic (no fabricated state when untrusted input given) | Not built |

**Total built: 30/~220 target tasks (14%).**

## Scoring philosophy

Executable scoring (unit tests, exact structured-output/schema checks,
diff correctness) is preferred wherever the task shape allows it,
per this closure's own instruction -- category 1's existing keyword
coverage is the LEAST rigorous method in this suite and is retained
only because it already exists and covers real ground, not because
it's the target standard for new categories. LLM-judge scoring is
explicitly labeled non-deterministic/subjective wherever used and must
never be the sole evidence for a pass/fail qualification decision.

## Held-out policy

None of the 17 categories currently has a formally verified held-out
split independent from any training data (category 1 predates the
train/eval-split discipline `DatasetManifest`/`scripts/
build_genesis_v2_dataset.py` established this closure; categories 2-17
don't exist yet to have a split policy tested). **Before any category
is used to qualify a real checkpoint, its task set must be verified
disjoint from every training dataset's records** (the same exact-string
and near-duplicate checks `tests/test_genesis_v2_dataset_builder.py`
already implements for the Genesis v2 training data should be reused
for evaluation-set construction, not reinvented).

## Contamination policy

Not yet defined for any category beyond "not sourced from training
data." No policy exists yet for contamination against the base model's
own pretraining corpus (an inherent, hard-to-fully-resolve problem for
any evaluation of a model whose pretraining data isn't fully known --
flagged, not solved, here).

## Baseline-vs-candidate protocol

The SAME suite version must score both the untouched base model and
any Genesis-trained candidate (spec section 26/`PHASE21C_GENESIS_
TRAINING_RUNBOOK.md` Steps C and J). Per-category deltas, never a
single aggregate score, determine qualification -- a category
regression must be visible even if the aggregate average improves.

## Pass/fail interpretation

Not yet defined numerically for categories 2-17 (category 1 has no
formal pass/fail threshold either -- `genesis_eval.py` reports a raw
score, and `docs/MODEL_CARDS.md::PERSONA_CLAIM_THRESHOLDS` defines
nano's threshold at the persona-claim-gating layer, a separate concern
from this suite). Defining real thresholds before any category exists
to threshold would be premature and is deliberately deferred.

## Limitations (honest, not glossed over)

- 14% built (task count), 6% built (category count, since category 1
  alone accounts for most of the 30 existing tasks).
- No executable scoring exists yet for ANY category -- category 1 uses
  keyword coverage, explicitly the weakest method this document
  recommends.
- No held-out verification exists for category 1's existing tasks.
- No contamination policy against base-model pretraining data.
- This document is a specification for Phase 21B.2 (or a dedicated
  future evaluation-build closure) to implement against, not a
  completed deliverable.
