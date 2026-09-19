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

**Purpose:** Tier-2 (`genesis-frontier-holdout-v1`) execution — reserved
for candidates that have demonstrated Stage 2/3 capability worth the
cost of spending sealed, harder-to-replace holdout tasks on them.

**Gate (promotion into this stage):** a candidate proceeds to Stage 4
only if its Stage 2/3 capability matrix shows it is plausibly
competitive (not already eliminated by a Stage 0 gate, and not already
showing a hard-gate failure) — this is a COST-EFFICIENCY promotion rule,
not a capability judgment; the exact promotion cutoff is set at
execution time based on how many candidates the credit-aware plan
(`GENESIS_FRONTIER_COST_PLAN.md`) can actually afford to run through the
more expensive holdout tier, never by pre-guessing which candidate will
"win."

**Elimination:** a candidate not promoted past this gate remains fully
recorded with its Stage 2/3 evidence — it is not scored on Tier-2 tasks
it never ran, and no inference is drawn about how it would have
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
the finalist set (candidates that passed Stage 4's promotion gate and
show no hard-gate failure through Stage 5) is re-run at native/BF16
precision on the full capability matrix, closing the quantization-
fairness question before any decision is finalized.

**Gate:** a finalist whose Round B results diverge materially from its
Round A results (per the quantization regression test,
`GENESIS_FRONTIER_SCORING_CONTRACT.md` §8.3) has its Round A results
marked unreliable and Round B treated as authoritative — this can
change (never silently ignore) which candidates remain competitive.

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

## Promotion/elimination summary

| Stage boundary | Eliminates on | Never eliminates on |
|---|---|---|
| 0 → 1 | License/identity/runtime ineligibility | Capability |
| 1 → 2 | Infrastructure/pipeline failure | Capability |
| 2 → 3 | (none — informational) | — |
| 3 → 4 | Cost-efficiency promotion cutoff, or a hard-gate failure already evident | Being merely "not the top scorer" at this point |
| 4 → 5 | (none — scoring resolution only) | — |
| 5 → 6 | Hard-gate failure confirmed through human adjudication | Capability score alone |
| 6 → 7 | Quantization-revealed unreliability (reclassifies evidence, does not by itself eliminate) | — |
| 7 → 8 | Objectively infeasible serving design | Merely higher infrastructure cost |

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
GPU kernels, batching, or distributed inference configurations.

- **Deterministic-like settings** (common-core config, temperature 0):
  verify repeat stability on a fixed, representative subset (the same
  subset used for the quantization regression test, §8.3 of the scoring
  contract, reused here for efficiency) by running it at least twice and
  confirming the pass/fail outcome is stable per task. A task whose
  outcome flips between repeats is flagged as unstable and excluded from
  that category's point-estimate calculation until investigated (never
  silently averaged in as if it were stable).
- **Stochastic/reasoning-budget tracks**: the number of samples per task
  is fixed and recorded before execution (not chosen after seeing early
  results). Best-of-N scoring is **not used** to inflate any candidate's
  score unless (a) every candidate receives the identical best-of-N
  protocol, AND (b) best-of-N sampling is an explicit, intended part of
  ORNEUR's actual product runtime for Genesis (i.e., the product itself
  will sample N times and select — not merely a benchmark-time trick).
  Absent both conditions, single-sample scoring is used for every
  candidate.
