# Genesis Frontier Execution Plan

**Phase 21B.4.9 — STAGED FUNNEL DESIGN ONLY.** No stage below is
executed in this phase. This document defines the funnel a future,
separately authorized execution phase must follow, in order, with
explicit promotion/elimination rules at each boundary.

## Staged funnel

### Stage 0 — License / identity / runtime eligibility

**Gate:** a candidate proceeds only if all of the following pass:
- License permits the intended use (deployment; fine-tuning if the
  candidate is being considered as a foundation base; distillation if
  being considered as a teacher or student) — checked against
  `GENESIS_FRONTIER_DECISION_GATES.md` §C.
- Exact revision resolvable and pinnable (not a mutable API-only
  identity, unless the candidate is explicitly being evaluated as a
  REFERENCE only).
- A runtime path exists (vLLM/SGLang/transformers, per
  `GENESIS_FRONTIER_COMPUTE_MATRIX.md`) at some qualified compute
  resource.

**Elimination:** a candidate that fails Stage 0 is recorded as
ineligible, with the specific failing sub-check, and proceeds no
further. No candidate is silently dropped without this record.

### Stage 1 — Cheap control + smoke subset

**Purpose:** verify the pipeline itself works for this candidate
(generation succeeds, output is well-formed, the artifact-provenance
chain completes end to end) before spending real compute on the full
suite.

**Gate:** a small, fixed cross-category smoke subset (the same subset
for every candidate, not cherry-picked per candidate) must complete
with zero generation failures attributable to infrastructure (timeouts,
malformed output the adapter cannot parse, artifact-chain integrity
errors). A capability failure on the smoke subset is not eliminating at
this stage — only an infrastructure failure is.

### Stage 2 — Common deterministic/public suite

**Purpose:** full Tier-1 (`genesis-eval-v1`) run under the common-core
config (`GENESIS_FRONTIER_SCORING_CONTRACT.md` §6.1), Round A
(screening) precision.

**Gate:** completeness (every task accounted for, per the existing
denominator-integrity enforcement) is mandatory — an incomplete run is
not scored, it is re-attempted or the candidate is flagged for
investigation. Capability results here do not eliminate a candidate on
their own; they establish the baseline capability matrix carried
forward.

### Stage 3 — Hard public tasks

**Purpose:** the frontier/extreme-band subset of Tier-1 (where such
tasks exist) plus any capability-appropriate extension runs (long
context, reasoning-enabled track) applicable to this candidate.

**Gate:** none eliminating — this stage exists to populate the
capability matrix's harder rows before the private holdout is spent on
a smaller finalist pool (Tier-2 execution is more expensive per task,
by design, since it demands genuinely difficult content).

### Stage 4 — Sealed frontier holdout

**Purpose:** Tier-2 (`genesis-frontier-holdout-v1`) execution — the
decisive frontier-discrimination benchmark for the foundation
comparison.

**Gate (promotion into this stage) — CORRECTED, Phase 21B.4.9.1:** an
independent audit found the prior version of this gate let COST/CREDIT
availability decide which otherwise-eligible candidates received the
decisive benchmark — this is removed. The owner's doctrine is explicit:
a ₹0 cash constraint may DELAY an evaluation; it must never LOWER the
intelligence standard or ELIMINATE an otherwise-eligible candidate
merely because credits are temporarily insufficient.

**New rule:** any deployable Genesis candidate (class B), and any
registered frontier reference or control required by a registered
comparator (`GENESIS_FRONTIER_DECISION_GATES.md` §"Frontier reference
set" / §"Control superiority"), that:
- passes Stage 0 eligibility,
- completes valid Stage 1-3 evidence, and
- has no CONFIRMED hard-gate failure,

**remains eligible** for the sealed Tier-2 frontier holdout — full
stop. Eligibility is never re-litigated based on how "competitive" the
Stage 2/3 numbers look; that would reintroduce a capability-based
elimination at a stage this plan reserves for eligibility/hard-gate
checks only.

**If credits are insufficient to run every eligible candidate through
Stage 4 immediately:** the affected candidate's status is recorded as
`DEFERRED_FOR_COMPUTE` — explicitly **not** `ELIMINATED`,
`NOT_PROMOTED`, or `TOO_EXPENSIVE`. A `DEFERRED_FOR_COMPUTE` candidate:
- is never treated as having failed or lost the comparison;
- is never silently replaced with a weaker/cheaper candidate to fill
  its slot;
- resumes Stage 4 execution as soon as additional legitimate zero-cash
  compute becomes available — next-monthly Modal credits, Race FLOPs/
  free rewards, Lightning AI credits (once separately qualified —
  currently `NOT_QUALIFIED`, Phase 21B.4.5), startup/research grants, or
  any other legitimate ₹0-cash-compliant compute source
  (`GENESIS_FRONTIER_COST_PLAN.md`).
- if a registered frontier reference or control cannot receive the
  required holdout tasks for a comparator computation, THAT COMPARISON
  is marked `INCOMPLETE — REFERENCE/CONTROL DEFERRED_FOR_COMPUTE` rather
  than silently computed over a smaller or substitute set, mirroring the
  `REFERENCE_UNAVAILABLE` handling in `GENESIS_FRONTIER_DECISION_GATES.md`.

**Elimination at this stage now occurs ONLY for:**
- Stage 0 ineligibility (already excluded before reaching Stage 4), or
- a hard-gate failure CONFIRMED (not merely suspected) through Stage
  1-3 evidence and human adjudication where required.

A candidate legitimately eliminated (as opposed to deferred) remains
fully recorded with its Stage 1-3 evidence — it is not scored on Tier-2
tasks it never ran, and no inference is drawn about how it would have
performed there.

### Stage 5 — Judge / human adjudication

**Purpose:** run the multi-layer judge protocol
(`GENESIS_FRONTIER_SCORING_CONTRACT.md` §3) over every judge-required
category item collected in Stages 2-4, plus any hard-gate-flagged item
requiring human adjudication.

**Gate:** none eliminating — this stage resolves scores for
already-collected responses; it does not generate new candidate
responses.

### Stage 6 — High-precision finalist revalidation

**Purpose:** Round B (`GENESIS_FRONTIER_SCORING_CONTRACT.md` §8.2) —
closing the quantization-fairness question before any decision is
finalized.

**Promotion into Round B — CORRECTED, Phase 21B.4.9.1:** promotion must
not depend on cost convenience any more than Stage 4's did. Any
deployable candidate that is, per `GENESIS_FRONTIER_DECISION_GATES.md`'s
frontier-class threshold:
- **frontier-non-inferior** on any critical category, OR
- **INCONCLUSIVE** relative to the frontier threshold on any critical
  category (§5.3 of the scoring contract — inconclusive is never
  resolved downward without more evidence), OR
- flagged as **potentially harmed by Round-A quantization** (its
  Round-A precision was NOT CERTIFIED for a critical category per
  `GENESIS_FRONTIER_SCORING_CONTRACT.md` §8.3),

**must receive Round-B high-precision revalidation before final
exclusion from foundation consideration.** If credits are insufficient,
the candidate's Round-B status is `DEFERRED_FOR_COMPUTE` (identical
semantics to Stage 4's rule) — an inconclusive or quantization-suspect
result is never resolved downward (treated as a failure) merely because
verifying it costs more compute.

**Gate:** a finalist whose Round B results diverge materially from its
Round A results (per the quantization regression test,
`GENESIS_FRONTIER_SCORING_CONTRACT.md` §8.3) has its Round A results
marked unreliable and Round B treated as authoritative — this can
change (never silently ignore) which candidates remain competitive. A
candidate is only finally excluded from foundation consideration at
this stage if its Round-B (authoritative) results confirm a material
gap or a hard-gate failure — never on the strength of a Round-A result
alone once Round-B was owed to it under the rule above.

### Stage 7 — Serving / operational characterization

**Purpose:** for every finalist still standing after Stage 6, produce
the serving-feasibility section (`GENESIS_FRONTIER_EVIDENCE_SCHEMA.md`
§10K serving fields) — replica topology, GPU count, parallelism
strategy, continuous batching, KV-cache footprint, autoscaling,
routing, failover. This is characterization, explicitly **not** a
10,000-user load test (owner spec §29) — the benchmark does not need to
prove the infrastructure at scale, only estimate it credibly.

**Gate:** a finalist is eliminated at this stage ONLY if its serving
design is objectively infeasible under any credit-aware plan ORNEUR can
actually execute (`GENESIS_FRONTIER_DECISION_GATES.md` §F) — not merely
more expensive or complex than an alternative.

### Stage 8 — Foundation decision package

**Purpose:** assemble the complete evidence package (capability matrix,
frontier-gap report, hard-gate results, adaptability evidence, licensing
status, serving feasibility, cost/latency data) for every surviving
finalist, in the format `GENESIS_FRONTIER_EVIDENCE_SCHEMA.md` defines,
and present it for the owner's foundation-strategy decision. **This
stage does not itself select a winner** — it produces the package a
human decision is made from.

## Promotion/elimination summary (CORRECTED — Phase 21B.4.9.1)

| Stage boundary | Eliminates on | Defers on (never eliminates) | Never eliminates on |
|---|---|---|---|
| 0 → 1 | License/identity/runtime ineligibility | — | Capability |
| 1 → 2 | Infrastructure/pipeline failure | — | Capability |
| 2 → 3 | (none — informational) | — | — |
| 3 → 4 | Stage 0 ineligibility already excluded; confirmed hard-gate failure | Insufficient compute (`DEFERRED_FOR_COMPUTE`) | Being merely "not the top scorer," or cost/credit availability |
| 4 → 5 | (none — scoring resolution only) | — | — |
| 5 → 6 | Hard-gate failure confirmed through human adjudication | — | Capability score alone |
| 6 → 7 | Round-B-confirmed material gap or hard-gate failure | Insufficient compute for owed Round-B (`DEFERRED_FOR_COMPUTE`) | An inconclusive or quantization-suspect Round-A result alone, before Round-B it is owed |
| 7 → 8 | Objectively infeasible serving design | — | Merely higher infrastructure cost |

## Artifact provenance requirement (applies to every real run, every stage)

Every real candidate run in Stages 1-6 MUST use the already-qualified
chain, with no stage permitted to bypass any link:

```
trusted inference worker (Modal GPU / other qualified compute)
  → RemoteGenerationRecord (orca.eval.runner)
  → orchestrator-side coverage validation (materialize_generation_artifact)
  → canonical, content-addressed raw-response persistence
  → GenerationArtifactManifest
  → seal (seal_generation_artifact / write_sealed_generation_artifact)
  → independently-retained digest (sidecar .sha256, separate from the .json blob)
  → transfer
  → verified receipt (load_and_verify_generation_artifact -> VerifiedGenerationArtifact)
  → identity validation (verify_manifest_identity)
  → raw-response validation (SHA-256 + byte_length)
  → scoring (score_verified_generation_artifact -- the ONLY real-benchmark scoring entry point)
  → provenance-stamped EvaluationResultManifest (provenance_kind="real_generation_artifact", digest, schema_version -- auto-stamped, never manually set)
  → final provenance re-verification at baseline-finalization time (orca.eval.baseline._validate_result_generation_provenance -- re-reads the sealed artifact from disk, closing the TOCTOU window)
  → suite freeze (record_baseline_and_freeze_suite)
```

`run_suite()` and the legacy `run_scoring_phase_from_artifact()` remain
harness/dry-run-only (Phase 21B.4.8.3) and produce
`provenance_kind="synthetic_test"` — **no execution-plan stage may use
either as the path for a real candidate's scored result**; they exist
solely for pipeline smoke-testing (Stage 1's infrastructure check may
use them internally to validate plumbing, but the RESULT that stage
produces for a real candidate must still go through the full chain
above before Stage 2 accepts it as evidence).

## Pre-freeze evidence-preservation gate (mandatory, execution-protocol level)

Carried forward from the Phase 21B.4.8.3 independent-audit note: before
the FIRST real baseline is allowed to freeze `genesis-eval-v1` (or any
future suite version), the execution protocol MUST perform a dedicated
pre-freeze check, distinct from and in addition to
`_validate_result_generation_provenance()`'s existing bundle-level
re-verification:

- Re-verify the sealed `GenerationArtifactManifest` (already required by
  `record_baseline_and_freeze_suite()`).
- For **every** non-error record in that manifest, independently confirm:
  - its `raw_response_ref` still resolves to an existing file;
  - the file's byte length still matches the manifest's recorded
    `byte_length`;
  - the file's SHA-256 still matches the manifest's recorded
    `text_sha256`.
- Confirm the manifest's task coverage is still complete against the
  live-verified suite (re-running `verify_against_suite()`, not merely
  trusting the scoring-time result).

**This phase does not implement or run this check.** It is recorded
here as a MANDATORY GATE that the execution phase's tooling must add
(a small, well-scoped addition to `orca.eval.baseline` or a dedicated
pre-freeze helper — not a redesign) before the first real baseline is
permitted, because `_validate_result_generation_provenance()` currently
re-verifies the sealed BUNDLE's bytes but does not re-walk every
individual raw-response file's continued existence/integrity at
finalization time — those live in a separate content-addressed store
from the bundle bytes themselves, so a bundle-level re-hash alone does
not prove every raw response file is still intact. Closing this is
explicitly deferred to the execution-authorization turn, consistent with
this phase's "methodology only, minimal code changes only when clearly
required" scope — and this gap is not itself exploitable for a false
POSITIVE baseline today (a corrupted raw response would still be caught
at read time if anything ever re-reads it, and no automated process
currently re-reads it after scoring) but must not be left unaddressed
before real execution begins.

**Restated as a HARD IMPLEMENTATION PREREQUISITE (Phase 21B.4.9.1):**
Phase 21B.4.10 (the proposed candidate-execution qualification gate,
not yet started) MUST implement this check before any real candidate
execution is permitted to call `record_baseline_and_freeze_suite()`
against `genesis-eval-v1` or any future suite version. This is not
optional scope for that phase — it is a precondition, exactly as
carried forward from Phase 21B.4.9's own finding.

## Sample size / power / resolution planning (LOCKED methodology, no tasks authored)

Before any private holdout task is authored, the methodology must be
sized to actually support the margins locked in
`GENESIS_FRONTIER_SCORING_CONTRACT.md` §5.4 — authoring tasks first and
discovering the suite is underpowered would waste the exact scarce,
hard-to-replace holdout content this tier exists to protect.

### Theoretical bounded worst-case variance — CORRECTED (Phase 21B.4.9.2)

An independent audit correctly identified a mathematical error in the
prior version of this section: it called `sigma_D^2 = 0.25` "the
maximum possible variance" for the paired difference `D`. That is
wrong. Each per-task score is normalized to `[0,1]`
(`GENESIS_FRONTIER_SCORING_CONTRACT.md` §5.1), so `D = candidate_score -
comparator_score` ranges over `[-1, 1]`, not `[0,1]` — `0.25` is the
maximum variance of a SINGLE `[0,1]`-bounded Bernoulli variable
(achieved at `p=0.5`), not of their DIFFERENCE. The correct theoretical
bound for a variable confined to `[-1,1]` is `Var(D) ≤ 1` (achieved in
the degenerate case where `D` places all its probability mass at the
two endpoints `±1`).

**Worked power calculation, corrected (methodology only — no candidate
data used):** for a paired-difference test at 95% confidence (two-sided,
`z_{0.025} = 1.96`) and 80% power (`z_{0.20} = 0.84`), detecting an
effect size `delta` against the THEORETICAL BOUNDED WORST-CASE variance
`sigma_D^2 = 1`:

```
n ≈ (z_{alpha/2} + z_{beta})^2 * sigma_D^2 / delta^2
```

For `delta = delta_frontier = 0.08`:
`n ≈ (1.96 + 0.84)^2 * 1 / 0.08^2 = 7.84 * 1 / 0.0064 ≈ 1225` paired
tasks per critical category, under the theoretical bounded worst-case
variance assumption.

**This is a THEORETICAL BOUNDED-WORST-CASE PLANNING NUMBER, not a
recommendation that ORNEUR must author 1,225 tasks per category.** The
bound `sigma_D^2 = 1` is achieved only when the paired difference is
maximally spread between its two extreme values on every task — an
extreme, unrealistic case. Actual paired-difference variance is
expected to be MATERIALLY LOWER in practice for two structural reasons:
(1) each individual term is itself `[0,1]`-bounded with its own
realistic variance well below the single-variable maximum of `0.25` for
most well-constructed tasks (tasks are rarely exactly 50/50 coin-flips);
and (2) — the more important reason — candidate and comparator
performance on the SAME task is genuinely CORRELATED (both a strong
candidate and a strong reference tend to succeed on easy tasks and
struggle on the same hard tasks), and `Var(A - B) = Var(A) + Var(B) -
2·Cov(A,B)` shrinks as that positive covariance grows. This correlation
is exactly why the paired-bootstrap design (§5.2 of the scoring
contract) is used in the first place, rather than treating candidate
and comparator as independent samples — and it means the realistic
required sample size is expected to be well below the 1,225-task
theoretical ceiling, though this methodology does not simply assert a
specific lower number without evidence (see the pilot/calibration
policy below).

### Holdout sizing policy — pilot evidence, not a decision-capable claim (Phase 21B.4.9.2)

The prior version of this document implied a **40-60 task per critical
category** figure could serve as a practical floor for resolving the
locked `delta_frontier = 0.08` non-inferiority question. An independent
audit correctly rejected this: a range roughly 10-30× smaller than even
a realistically-improved sample-size estimate cannot be presented as
sufficient to prove an 8-point non-inferiority margin, and doing so
would let benchmark discrimination quietly loosen without ever changing
the (correctly locked) numeric threshold itself. **40-60 tasks per
category is reclassified as a PILOT / INITIAL EVIDENCE FLOOR only — NOT
a decision-capable holdout size.** A holdout authored to only this size
should expect `INCONCLUSIVE` results on `delta_frontier`-level questions
for most critical categories, and that expectation is itself useful
pilot information, not a discovered fact this document can currently
assert as sufficient.

**Required process before final private holdout authoring (methodology
only — no tasks authored this phase or by this process):**

1. Author (in a future, separately authorized phase) a **separate,
   NON-DECISION pilot/calibration task set** — smaller, explicitly
   never used for an actual frontier-class determination — to estimate
   the REAL, empirical paired-difference variance for each critical
   category, using early candidate/reference/control evidence. This
   set is spent specifically so its consumption does not deplete the
   sealed final holdout's own discriminating power.
2. From the pilot set's measured `Var(D)` per critical category
   (expected, per the correlation argument above, to be well below the
   theoretical `sigma_D^2 = 1` ceiling, but measured rather than
   assumed), recompute the required final-holdout sample size using the
   SAME formula and the SAME locked margins/confidence/power targets
   (`delta_frontier = 0.08`, 95% confidence, 80% power) — never a
   loosened margin or a lowered confidence/power target substituted to
   make a smaller number "work."
3. **Round the resulting sample size upward conservatively** (not down,
   and not to the nearest convenient/cheap number) when translating it
   into an actual authored task count.
4. **Never estimate the required sample size from the FINAL candidate
   results themselves, after seeing them** — that would let observed
   variance be reverse-engineered into whatever sample size makes an
   already-known outcome look adequately powered, which is exactly the
   kind of post-hoc statistical manipulation this methodology exists to
   prevent.

**If, despite this process, the actually-available evidence remains
underpowered for a given category:** the result is `INCONCLUSIVE` for
that category. `delta_frontier` (or any other locked margin) is NEVER
loosened to manufacture a resolvable-looking answer from underpowered
data — this restates, with the corrected math, the same rule the prior
phase locked.

**Binary/pass-fail vs. normalized-rubric scoring** still changes the
per-term contribution to variance (a rubric's own granularity affects
its individual-term variance, per-task, before pairing), but the
CORRECTED overall bounding logic above (worst case `sigma_D^2 = 1` for
the paired difference, refined downward only by measured pilot
evidence, never by assumption) applies uniformly to both scoring types
— no scoring type is assumed lower-variance without the pilot-
calibration evidence in step 2 above to support it.

**No private task content is authored this phase** — this section fixes
the SIZING METHODOLOGY (and its correct underlying mathematics) future
task authoring must satisfy, not the tasks themselves.

## Release-date / contamination record (§25)

For every candidate eventually evaluated, the evidence package
(`GENESIS_FRONTIER_EVIDENCE_SCHEMA.md`) records:

- Model exact revision (already enforced structurally via
  `CandidateConfig.exact_revision`).
- Revision timestamp (from the model's own repository metadata).
- Model release date (as publicly documented by the provider).
- Public benchmark (`genesis-eval-v1`) creation date — 2026-09-17,
  unchanged.
- Private holdout (`genesis-frontier-holdout-v1`) creation date — not
  yet set, since it is unauthored.

**Contamination posture classification**, unchanged in mechanism from
`GENESIS_FRONTIER_HOLDOUT_SPEC.md`: a candidate whose exact revision
predates the holdout's creation timestamp is marked `POST-REVISION
HOLDOUT`, which strongly reduces (never eliminates — a model could still
have been retrained/updated after its stated revision date in ways not
fully disclosed) direct training-data contamination risk. Zero-
contamination is never claimed as proven — only the relative evidentiary
strength of a `POST-REVISION HOLDOUT` classification versus one that
postdates the holdout.

## Repeated runs / variance policy (§26)

Temperature-0 sampling does not guarantee bit-for-bit determinism across
GPU kernels, batching, or distributed inference configurations. The
exact numeric repeat policy is now LOCKED in
`GENESIS_FRONTIER_SCORING_CONTRACT.md` §8.4 (3 repeats, on the same
calibration subset used for the quantization regression test, with an
explicit `UNSTABLE`/`INCONCLUSIVE` outcome and a locked prohibition on
best-of-N absent an explicit matching product-runtime decision) — this
section restates the policy's role in the execution funnel rather than
re-deriving it:

- **Deterministic-like settings** (common-core config, temperature 0):
  the §8.4 stability check runs on the calibration subset for every
  candidate at both Round A and Round B; an `UNSTABLE` task is excluded
  from that category's point-estimate calculation until investigated —
  never silently averaged in as if it were stable.
- **Stochastic/reasoning-budget tracks**: the number of samples per task
  is fixed and recorded before execution (not chosen after seeing early
  results), per §8.4's best-of-N prohibition — absent an explicit,
  matching product-runtime decision applied identically to every
  candidate, single-sample scoring is used for every candidate.
