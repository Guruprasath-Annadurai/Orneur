# Genesis Frontier — Next Gate

## Phase 21B.4.10 update

Turned the locked Phase 21B.4.9.x methodology into an enforceable,
tested, execution-ready gate, WITHOUT evaluating a real Genesis
candidate:

1. **Mandatory pre-freeze raw-evidence gate implemented**
   (`orca.eval.baseline._verify_raw_evidence_before_freeze()`, carried
   forward from the Phase 21B.4.8.3 audit finding): immediately before
   any real baseline finalizes, every successful generation record's
   raw response is independently re-verified on disk (existence,
   canonical-artifact-root containment, byte_length, SHA-256, UTF-8
   decodability), and the manifest is re-reconciled against the live
   suite — closing the TOCTOU window where `_validate_result_generation_
   provenance()`'s bundle-level re-hash alone did not prove every
   individual raw-response file was still intact. 12 adversarial tests
   (`tests/test_pre_freeze_raw_evidence.py`) prove the suite remains
   unfrozen on every attack (deletion, byte modification, truncation,
   byte-length/hash tampering, missing/unknown/duplicate records, path
   escape, full replacement) and proceeds when all evidence is intact.
2. **The locked statistical contract is now executable code**
   (`orca/eval/frontier_stats.py`, `FRONTIER_STATISTICAL_CONTRACT_VERSION
   = "genesis-frontier-stats-v1"`): all five locked margins
   (`delta_frontier`, `delta_best_reference`, `delta_control_superiority`,
   `delta_tie`, `delta_quantization`), the judge-disagreement threshold,
   the stability repeat count, and both quorum requirements are single-
   sourced constants, never scattered magic numbers. A cluster-aware
   paired bootstrap (`StatisticalUnit`, `paired_bootstrap_ci()`) closes
   an audit-flagged gap: related task variants (sharing a scenario/
   source/template/fixture) are resampled together, never as
   independent observations — proven by a dedicated test showing the
   clustered treatment yields a correctly wider (more honest) confidence
   interval than treating the same tasks as independent. 32 tests, all
   synthetic fixtures, no candidate data.
3. **Stage-0 identity/license/runtime eligibility performed** for the
   full candidate pool via live Hugging Face Hub API metadata calls
   (no weight shards downloaded): `docs/orneur/phase-21/
   GENESIS_CANDIDATE_EXECUTION_REGISTRY.json` (schema-validated by
   `orca/eval/candidate_registry.py`, 18 tests) records exact pinned
   revisions, licenses, architectures, and parameter breakdowns for all
   4 deployable candidates, 3 controls, and 6 frontier references.
   Findings: Mistral Small 4 and GLM-5.3-Flash both ship OFFICIAL FP8
   checkpoints (not a hypothetical conversion); Qwen3.8-Flash-Next
   remains `LICENSE_REVIEW_REQUIRED`; all four deployable candidates use
   architecture classes not previously runtime-qualified by this
   project (`GENESIS_RUNTIME_COMPATIBILITY_MATRIX.md`).
4. **Zero-cash compute reverified, read-only**: current Modal billing
   (`billed_cost: $0.00`, unchanged) and GPU rate card reconfirmed live;
   the workspace's dashboard-set $0 spend limit is explicitly NOT
   re-claimed as programmatically reverified (the supported CLI does not
   expose it) — `GENESIS_ZERO_CASH_EXECUTION_PLAN.md` states this
   distinction plainly. No GPU started, no weights downloaded, no API
   called, no persistent Volumes created.
5. **`GENESIS_FRONTIER_HOLDOUT_SPEC.md` extended** with the mandatory
   `statistical_unit_id` requirement for any future task authoring, so
   related task-variant families are never bootstrapped as independent
   observations.

No candidate was evaluated; `genesis-eval-v1` was not executed, inspected,
or frozen; no private holdout content was authored; no candidate was
downloaded, loaded, or launched on GPU; Phase 21C remains unauthorized.

## Phase 21B.4.9.2 update

An independent audit of Phase 21B.4.9.1 found further mathematical and
compute-envelope errors. Closes all, docs-only:

1. **Corrected the paired-difference variance bound.** `D = candidate -
   comparator` is bounded on `[-1,1]` (not `[0,1]`), so the theoretical
   worst-case variance is `sigma_D^2 = 1`, not the `0.25` figure the
   prior phase incorrectly called a worst case (that number is the max
   variance of a single `[0,1]`-bounded term, not their difference). The
   corrected worked power calculation now shows `n ≈ 1,225` paired
   tasks per critical category as the THEORETICAL BOUNDED WORST-CASE
   planning number (explicitly not a task-authoring target — real
   variance is expected far lower given candidate/reference performance
   correlation on shared tasks) (`GENESIS_FRONTIER_EXECUTION_PLAN.md`
   §"Sample size / power / resolution planning").
2. **Reclassified the 40-60 task/category floor** from an implied
   "sufficient for decision" size to an explicit **PILOT / INITIAL
   EVIDENCE FLOOR only**, and added a required pilot-calibration process
   (a separate, non-decision task set measures real paired-difference
   variance, which then sizes the final sealed holdout — never the
   final holdout's own results used to retroactively justify its size).
3. **Fixed the tie/practical-equivalence classification** to an exact,
   gap-free four-way partition (equivalent / A-ahead / B-ahead /
   inconclusive) with locked worked examples
   (`GENESIS_FRONTIER_SCORING_CONTRACT.md` §5.5).
4. **Fixed the best-reference ceiling guard** to a three-state
   classification (`CEILING-NONINFERIOR` / `DRAMATICALLY BEHIND
   CEILING` / `INCONCLUSIVE`), closing a gap where an unresolved
   (straddling) interval could have silently passed as ceiling-
   noninferior (`GENESIS_FRONTIER_DECISION_GATES.md`).
5. **Locked a frontier reference quorum** (≥4 of 6 registered
   references, spanning ≥3 independent organizations/lineages) and a
   **control comparator quorum** (all 3 registered controls required) —
   below quorum, the comparison is `REFERENCE_SET_INCOMPLETE` /
   `CONTROL_SET_INCOMPLETE` and `INCONCLUSIVE/DEFERRED`, never silently
   computed over a degraded subset.
6. **Corrected two compute-table arithmetic errors** and separated
   THEORETICAL from PRACTICAL GPU counts throughout: Qwen3.8-Flash-Next's
   FP8 minimum is 3×80GB-class GPUs (not 2× — 2×80GB is physically
   insufficient for its ~180GB weight floor), and GLM-5.3-Flash's INT4
   minimum is 2×80GB-class GPUs (not 7× — that figure was an erroneous
   carry-over from an L4-based calculation). Every candidate now carries
   an explicit `QUALIFIED PRACTICAL GPU TOPOLOGY = UNQUALIFIED / TBD`
   field until live runtime qualification occurs, and every derived cost
   figure is tagged `PRELIMINARY / NOT EXECUTION-AUTHORIZED`
   (`GENESIS_FRONTIER_COST_PLAN.md` §3.1-3.2).

The accepted Phase 21B.4.9.1 rule (compute shortage → `DEFERRED_FOR_COMPUTE`,
never eliminated) and the mandatory Phase 21B.4.10 pre-freeze
raw-response evidence-preservation prerequisite are both explicitly
UNCHANGED and carried forward without regression. No candidate was
downloaded, executed, or ranked this phase; no GPU was started; no
private holdout content was authored; `genesis-eval-v1` remains
unexecuted and unfrozen; Phase 21C remains unauthorized. Docs-only — no
code changed.

## Phase 21B.4.9.1 update

An independent audit of Phase 21B.4.9 accepted the overall framework
(candidate classes, tier separation, hardness bands, categories, judge/
human architecture, reasoning tracks, quantization rounds, provenance
requirements, failure taxonomy, 10K-serving separation, no-magic-score
rule) but found three methodology blockers, all now closed, docs-only:

1. **Cost-based capability elimination removed.** The Stage 3→4 (and
   Stage 6 promotion) gates no longer let credit availability decide
   which otherwise-eligible candidates receive the decisive sealed
   holdout / high-precision revalidation — a new `DEFERRED_FOR_COMPUTE`
   status replaces silent elimination, matching the owner's doctrine
   that a ₹0 cash constraint may delay evaluation but must never lower
   the intelligence standard or eliminate an eligible candidate
   (`GENESIS_FRONTIER_EXECUTION_PLAN.md` Stage 4/Stage 6, corrected).
2. **Statistical framework corrected and fully locked.** The frontier
   gap, control-superiority, tie-region, and quantization-regression
   checks now use one consistent **paired bootstrap over task IDs**
   (task as sampling unit, 10,000 resamples, 95% CI) rather than
   comparing standalone confidence intervals for overlap. A registered,
   pre-declared **frontier reference set** (six references, primary
   comparator = frontier-reference median, secondary = strongest
   reference as a ceiling guard) replaces the ambiguous "strongest
   reference vs. median" wording. Four numeric margins are now locked,
   before any candidate result exists: `delta_frontier = 0.08`,
   `delta_best_reference = 0.20`, `delta_control_superiority = 0.10`,
   `delta_tie = 0.03`, plus `delta_quantization = 0.05` and a normalized
   `0.15` judge-disagreement threshold
   (`GENESIS_FRONTIER_SCORING_CONTRACT.md` §5, §3, §8.3;
   `GENESIS_FRONTIER_DECISION_GATES.md`). A worked (conservative)
   power calculation and a pragmatic 40-60-task-per-critical-category
   floor are recorded for future holdout sizing
   (`GENESIS_FRONTIER_EXECUTION_PLAN.md` §"Sample size / power /
   resolution planning") — INCONCLUSIVE is locked as never resolving in
   a candidate's favor, at every one of these checks.
3. **Compute/cost assumptions corrected.** The prior "deployable
   candidates fit Modal L4" blanket claim is replaced with a
   candidate-specific compute/cost envelope: only Qwen3.8-27B (at INT4)
   fits a single L4; Qwen3.8-Flash-Next, Mistral Small 4, and
   GLM-5.3-Flash all require multi-GPU at every tabulated precision,
   consistent with `GENESIS_FRONTIER_COMPUTE_MATRIX.md`'s existing
   TOTAL-parameter-based weight-storage math
  (`GENESIS_FRONTIER_COST_PLAN.md` §3).

Also locked this phase: the multimodal scope is TEXT/REASONING-FIRST
and non-decisional unless the owner explicitly changes this before
execution (`GENESIS_FRONTIER_SCORING_CONTRACT.md` §6.3); reasoning-track
selection uses a pre-declared product-intent rule, never "whichever
track scores highest" (§7); a 3-repeat stability policy with an
explicit `UNSTABLE`/`INCONCLUSIVE` outcome and a locked best-of-N
prohibition (§8.4); a hosted-frontier-reference zero-cash rule
(`GENESIS_FRONTIER_COST_PLAN.md` §5) mirroring the compute-deferral rule
for GPU-hosted candidates. The Phase 21B.4.9 pre-freeze raw-response
evidence-preservation finding is restated as a HARD implementation
prerequisite for Phase 21B.4.10, not optional scope
(`GENESIS_FRONTIER_EXECUTION_PLAN.md`).

No candidate was downloaded, executed, or ranked this phase; no private
holdout content was authored; `genesis-eval-v1` remains unexecuted and
unfrozen; Phase 21C remains unauthorized. Docs-only — no code changed.

## Phase 21B.4.9 update

The benchmark methodology proposed at the end of Phase 21B.4.8.1 (below)
is now DESIGNED, not yet executed. Six new documents lock the rules a
future execution phase must follow: `GENESIS_FRONTIER_BENCHMARK_METHODOLOGY.md`
(candidate classes, two-tier structure, category framework, hardness
bands, code/long-context/agentic/multimodal tracks), `GENESIS_FRONTIER_SCORING_CONTRACT.md`
(scoring types, judge protocol extensions, no-magic-number aggregate
rule, inference/reasoning-mode/quantization fairness, statistical
discipline), `GENESIS_FRONTIER_DECISION_GATES.md` (the six-dimension
foundation rubric, frontier-gap metric, frontier-class threshold, hard
gates, teacher/student evidence requirements), `GENESIS_FRONTIER_EXECUTION_PLAN.md`
(the 9-stage funnel with explicit promotion/elimination rules, the
artifact-provenance chain requirement, the pre-freeze evidence-
preservation gate carried forward from Phase 21B.4.8.3's audit note,
contamination and repeat-run policy), `GENESIS_FRONTIER_EVIDENCE_SCHEMA.md`
(the failure taxonomy and the full per-candidate evidence record every
finalist's package must contain), and `GENESIS_FRONTIER_COST_PLAN.md`
(₹0 out-of-pocket strategy, screen-cheaply-reserve-expensive-runs-for-
finalists discipline, zero spend this phase). No candidate was
downloaded, executed, or ranked; no aggregate weighting formula was
chosen; no judge model was selected; no private holdout content was
authored; `genesis-eval-v1` remains unexecuted and unfrozen; Phase 21C
remains unauthorized.

## Phase 21B.4.8.1 update

An independent audit of Phase 21B.4.8 found and this phase closed:
benchmark-integrity gaps in the generation/scoring split (durable
cross-machine generation artifacts, fail-closed denominator integrity
-- see `GENESIS_BENCHMARK_INTEGRITY_CONTRACT.md`), an incomplete
deployable-frontier landscape (added Qwen3.8-Flash-Next and Mistral
Small 4, corrected MiniMax M3's license and the Qwen3.8-Max/open-weight
identity distinction -- see the updated
`GENESIS_FRONTIER_MODEL_LANDSCAPE_2026_09.md`), and designed (without
authoring or running) two further specs: a private sealed frontier
holdout tier (`GENESIS_FRONTIER_HOLDOUT_SPEC.md`) and a multi-layer
judge protocol (`GENESIS_JUDGE_PROTOCOL_SPEC.md`). Modal's basic GPU
qualification (Phase 21B.4.8: CUDA/bf16/fp8 confirmed) was extended
with a real inference-engine runtime qualification this phase -- see
Section I of this phase's stop report for the live result. No frontier
model evaluation, no `genesis-eval-v1` execution/freeze, and no
Genesis training occurred.

## Where Phase 21B.4.8 left things

- Genesis's foundation-model target is now formally
  `FRONTIER-CLASS INTELLIGENCE`, no longer implicitly capped at the
  8B/12B/14B shortlist from Phase 21B.3.
- Qwen3-8B, Mistral-Nemo-Instruct-2407, and Phi-4 are reclassified as
  CONTROL / SMALL-BASELINE CANDIDATES (spec section 19) — their prior
  infrastructure work remains valid and reusable.
- A live, current (Sept 2026) frontier landscape has been researched
  (`GENESIS_FRONTIER_MODEL_LANDSCAPE_2026_09.md`), with hardware math
  for every candidate (`GENESIS_FRONTIER_COMPUTE_MATRIX.md`), a
  teacher/student strategy framing (`GENESIS_TEACHER_STUDENT_STRATEGY.md`),
  and 10K-user serving implications
  (`GENESIS_10K_SERVING_IMPLICATIONS.md`).
- `ModalSandboxBackend` (both legacy and V2) remains NOT_QUALIFIED for
  untrusted generated-code execution (Phase 21B.4.7A/A.1/A.2's live
  CPU-limit finding stands, unchanged and unreinterpreted).
  `DockerSandboxBackend` remains the qualified scorer.
- Genesis's evaluation architecture now cleanly separates generation
  from scoring (`run_generation_phase()` / `run_scoring_phase()`,
  Phase 21B.4.8), so a future trusted-inference-only GPU worker never
  needs Docker locally.
- `genesis-eval-v1` remains unexecuted, unfrozen, and held out.

## Proposed next gate

**Phase 21B.4.10 is now COMPLETE** (see the Phase 21B.4.10 update
above) — Stage 0 identity/license/runtime eligibility is qualified for
the full candidate pool, the mandatory pre-freeze raw-evidence gate is
implemented and tested, and the locked statistical contract is now
executable code. The next step, if authorized, is a real (still
non-Genesis, still $0) CPU/GPU-level runtime-compatibility check: does
any candidate's architecture actually LOAD under a real inference
engine, and does the license status for `LICENSE_REVIEW_REQUIRED`
candidates resolve before any compute is spent on them.

Proposed phase name (not authorized, not started):
`PHASE 21B.4.11 — GENESIS CANDIDATE RUNTIME SMOKE QUALIFICATION`
— to attempt a real, minimal, non-Genesis runtime smoke test (loading a
tiny/cheap proxy checkpoint of each novel architecture class where one
exists, or the actual smallest deployable candidate — Qwen3.8-27B — at
INT4 on a single Modal L4, per the ordering in
`GENESIS_CANDIDATE_EXECUTION_QUALIFICATION.md`) to convert at least one
`QUALIFIED PRACTICAL GPU TOPOLOGY = UNQUALIFIED / TBD` entry into a
real, live-tested value — still NOT authorizing `genesis-eval-v1`
exposure, private holdout content, or any frontier-model evaluation.

## What remains explicitly locked

- Phase 21C (training, in any form)
- Canonical Genesis base change
- Any model promotion or "winner" declaration
- `genesis-eval-v1` execution, inspection, or freezing
- Any real candidate download or evaluation
- Private frontier-holdout task authoring
- Any aggregate scoring formula or judge-model selection
