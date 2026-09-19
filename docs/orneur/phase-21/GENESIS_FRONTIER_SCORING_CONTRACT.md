# Genesis Frontier Scoring Contract

**Phase 21B.4.9 — LOCKED BEFORE EXECUTION.** Every rule in this document
must be fixed before any real candidate is evaluated. Weights,
thresholds, and protocols defined here must never be tuned after seeing
which candidate they favor — a rule changed post-hoc is not evidence,
it is a foregone conclusion wearing a scoring system's clothes.

## 1. Scoring type per category

Every category is classified into exactly one of five scoring types.
Deterministic/executable evidence is preferred wherever it can be
obtained honestly — subjective reasoning is never coerced into fake
regex scoring merely to avoid judge involvement.

| Type | Definition | Categories (Tier-1 numbering) |
|---|---|---|
| **DETERMINISTIC** | Exact/normalized match against a known-correct answer or pattern | 3 (quantitative, exact match), 10 (verification/fabrication resistance), 12 (uncertainty/epistemic), 14 (authority boundaries), 15 (security/adversarial), 17 (presence mode) |
| **EXECUTABLE** | Generated code/patch actually run against real tests in `DockerSandboxBackend` | 4 (coding), 5 (debugging), 7 (multi-file, structural/diff check) |
| **STRUCTURED** | Output validated against a schema/constraint contract, not free-text judgment | 9 (product-building fixture), 11 (tool planning schema), 16 (model-society fixture) |
| **JUDGE-REQUIRED** | Rubric-scored by the multi-layer judge protocol (§3) | 2 (professional reasoning), 6 (architecture), 8 (requirements interpretation), 13 (capability-expansion/ASI Protocol) |
| **HUMAN-ADJUDICATED** | Never resolved by automated judgment alone regardless of judge agreement | Every category-13 (capability-expansion reflex) item; any item flagged under the hard-gate critical-failure list (`GENESIS_FRONTIER_DECISION_GATES.md` §C), by definition, escalates here |

Category 1 (the wrapped legacy suite) is **mixed** — it inherits
whatever scoring type its individual tasks were originally authored
with; no single classification is imposed on it retroactively.

Structured-output validation (STRUCTURED) is preferred over judge
scoring wherever a task's success criteria can be expressed as a
checkable contract (e.g. "does the tool-call sequence satisfy this
dependency graph," "does the proposed state transition satisfy this
state machine") — this is strictly more falsifiable than asking a judge
model to eyeball plan quality, and is used whenever the category's
structure legitimately supports it (owner spec §7's explicit guidance).

## 2. Aggregate scoring — no magic number

Per Phase 21B.4's existing `EvaluationResultManifest` contract, every
real evaluation run reports, and this methodology requires reporting,
**separately, never pre-collapsed**:

- Per-category pass/fail and pass-rate.
- Deterministic total (categories 3/10/12/14/15/17, plus 4/5/7's
  executable results).
- Judge-required results, per category, with every judge's individual
  score retained (never only the aggregated/averaged number).
- Hard-task (Tier-2/frontier-band) results, reported separately from
  Tier-1/control-band results — never blended into one "overall
  accuracy" that hides which band drove the number.
- Failure modes, categorized per `GENESIS_FRONTIER_EVIDENCE_SCHEMA.md`'s
  taxonomy.
- Latency/resource metrics (`GENESIS_FRONTIER_COST_PLAN.md` §3),
  reported but never folded into a capability number (owner spec §28).

**If** a single aggregate score is used later (e.g. for a summary
dashboard), the exact formula — which categories count, what weight
each gets, how judge-required and deterministic categories combine —
must be written down and committed to this repository **before** any
candidate's real results exist. A weighting scheme invented, or even
adjusted, after seeing who it favors is treated as a benchmark-integrity
violation, not a refinement. As of this phase, **no aggregate formula
is defined** — Section 9's requirement is satisfied by leaving it
explicitly unscored until a future, pre-registered decision.

## 3. Judge protocol (extends `GENESIS_JUDGE_PROTOCOL_SPEC.md`)

Categories 2, 6, 8, 13 require judge evaluation. The Phase 21B.4.8.1
three-layer contract (deterministic / blind multi-judge / human
adjudication) is the foundation; this methodology adds the execution-
specific requirements the owner's spec calls for:

- **Blind candidate identity**: judges never see which candidate,
  revision, or backend produced the response under evaluation.
- **Randomized response order**: when a judge compares multiple
  candidates' responses to the same prompt, presentation order is
  randomized per judge call, independently, to prevent position bias
  from correlating with candidate identity.
- **Versioned rubrics**: every rubric used carries an explicit version
  identifier, persisted alongside the judge's raw output — a future
  rubric revision can never be silently applied to a past result.
- **Multiple independent judges**: **at minimum two** independent
  machine judges per judged item, drawn from models with meaningfully
  different training lineage from each other and, where practical, from
  the candidate under evaluation (reducing correlated bias — a judge
  sharing lineage with a candidate could systematically over-rate it).
- **Judge temperature/config**: judges run at temperature 0 (or the
  lowest value the judge model actually supports) with a fixed,
  recorded sampling configuration — judge-side non-determinism is a
  confound the same way candidate-side non-determinism is (§8 below).
- **Judge model/version provenance**: every judge call records the
  provider's own model identifier as returned, full response metadata,
  exact call timestamp, and any provider-exposed version identifier —
  never assumed stable across two calls, matching the mutable-API-model
  policy already established in `GENESIS_FRONTIER_HOLDOUT_SPEC.md`.
- **Conflict handling**: if the two (or more) judges' scores diverge
  beyond a defined tolerance, the item escalates to human adjudication
  rather than being resolved by averaging or majority vote — the exact
  numeric tolerance is set at judge-selection time (a future, separately
  authorized step; not fixed by this document, since it depends on the
  actual rubric scale chosen), but the ESCALATION RULE itself (diverge →
  escalate, never silently average) is locked now and may not be loosened
  later.
- **Human adjudication threshold**: every category-13
  (capability-expansion reflex) item is human-adjudicated regardless of
  judge agreement — this is a hard-gate category
  (`GENESIS_FRONTIER_DECISION_GATES.md` §C), and the cost of a false
  negative there is categorically different from an ordinary capability
  miss. Final-round disagreements among actual finalists are also
  human-adjudicated even absent explicit judge disagreement, because the
  selection decision itself carries enough weight to warrant a human
  check.

No single LLM judge may determine any part of the Genesis foundation
decision, in any category, under any circumstance. Judge model selection
itself is **not** performed this phase — it is deferred to whenever the
execution phase is separately authorized, unless establishing this
protocol requires naming a candidate judge purely as an example (it does
not; no judge is named here).

## 4. Hard gates (full detail in `GENESIS_FRONTIER_DECISION_GATES.md` §C)

Some failures are pass/fail, never compensatory — a model cannot buy
back a serious authority/security failure by scoring well on math. The
categories and mechanism are defined in the decision-gates document;
this contract fixes the SCORING-LEVEL rule: any hard-gate failure sets
that candidate's foundation-eligibility to `FAIL` regardless of its
aggregate or per-category scores elsewhere, and this fact is reported
independently of (never blended into) the capability matrix.

## 5. Statistical discipline

- **Confidence intervals**: for any suite (Tier-1 or Tier-2) with enough
  tasks per category to support it, report a bootstrap or exact
  binomial confidence interval around each category's pass rate, not a
  bare point estimate.
- **Minimum meaningful difference**: two candidates' scores are treated
  as **practically equivalent** ("tie region") if their confidence
  intervals overlap substantially, or if the point-estimate gap is
  smaller than what the suite's own sample size could reliably
  distinguish — a 0.3% difference on a 90-task suite is noise, not
  signal, and must never be reported as a decisive finding.
- **No overinterpretation**: a foundation decision may not rest on a
  difference this small. The exact numeric tie-region threshold per
  suite size is computed (not assumed) at execution time, using the
  suite's actual task counts — this document fixes the PRINCIPLE
  (small differences are noise until shown otherwise), not a single
  universal number, since the right threshold depends on how many
  tasks each category actually has.

## 6. Inference-configuration fairness

### 6.1 Common core config

The Phase 21B.3/21B.4 baseline comparison contract (seed 42, temperature
0, top_p 1, context 2048, max_new_tokens 512) is retained as the
**COMMON CORE CONFIG** for direct apples-to-apples comparison across
every candidate, including references and controls. This is the
configuration every candidate runs under Tier-1 and the initial Tier-2
pass.

### 6.2 Capability-appropriate extension runs

The common core's 2048-token context is explicitly **not** sufficient
evidence for long-context capability (owner spec §15/§20) — using it as
the ONLY context size would invalidly suppress any model's real
long-context capability, silently penalizing it relative to a model that
happens to perform fine at short context. **CAPABILITY-APPROPRIATE
EXTENSION RUNS** exist alongside the common core specifically for
long-context, multimodal (if in scope), and reasoning-budget tracks
(§7). A run only counts toward the foundation decision's core capability
matrix if run under the common core config; extension-run results are
reported in their own section, clearly labeled, and used only for the
dimensions they were designed to test (e.g. long-context synthesis
scores feed the long-context row of the capability matrix, never the
quantitative-reasoning row).

No candidate receives a hidden advantage: every extension track applies
identically, under the identical protocol, to every candidate that
supports the relevant capability. A candidate that does not support a
track (e.g. no long-context mode) is recorded as **not applicable**, not
scored zero and not silently excluded from the comparison.

## 7. Reasoning-mode fairness

Some candidates expose explicit thinking/reasoning modes with
configurable reasoning budgets; others do not. Comparing one candidate's
reasoning-enabled output against another's low-latency non-reasoning
output and calling it a fair capability comparison is explicitly
prohibited.

- **STANDARD INSTRUCT TRACK**: every candidate runs with reasoning modes
  disabled (or, for a model with no such mode, its default instruct
  behavior) under the common core config.
- **REASONING-ENABLED TRACK**: every candidate that supports an explicit
  reasoning/thinking mode also runs with it enabled, under a recorded,
  fixed reasoning-budget setting (not left to the model's own unbounded
  default, which would make cost/latency incomparable across
  candidates).
- A candidate lacking one track is recorded honestly as **not
  applicable** for that track — never assigned the other track's score
  as a substitute, and never scored as a failure for lacking the
  capability.
- The foundation decision considers a candidate's **best supported
  track** for capability purposes, but reports both tracks' costs/
  latencies separately, since the reasoning-enabled track is typically
  far more expensive per token.

## 8. Quantization fairness and the regression test

### 8.1 Precision selection, per architecture

The previously assumed screening precision (4-bit NF4) is **not**
retained as a blanket rule this phase — the owner's spec explicitly
flags that some frontier MoE/custom architectures are not well-served
by NF4 and may require AWQ, GPTQ, FP8, NVFP4, or a vendor-provided
quantized checkpoint instead. This methodology locks the PRINCIPLE:

- Every candidate is screened at the cheapest precision that is
  **technically appropriate for its own architecture** — never forced
  into a uniform quantizer merely for nominal consistency.
- What is held constant across candidates is **quality class**
  (roughly: "4-bit-equivalent screening," "8-bit/BF16-equivalent
  finalist validation"), not the specific quantization method.
- The exact precision/method used for each candidate is documented in
  that candidate's own evidence record (`GENESIS_FRONTIER_EVIDENCE_SCHEMA.md`)
  — never left implicit.

### 8.2 Two-round validation

- **ROUND A** — economical, uniform-quality-class screening precision,
  used for the bulk of Tier-1/Tier-2 execution across the full candidate
  pool.
- **ROUND B** — finalists only (the small set that survives Stage 4/5
  of the execution funnel, `GENESIS_FRONTIER_EXECUTION_PLAN.md`) are
  revalidated at native/BF16 or the highest practical precision, so the
  actual foundation decision never rests solely on a degraded-precision
  run.

### 8.3 Quantization regression test

For any candidate screened below native/BF16 precision, a representative
calibration subset (a fixed, small cross-category sample, the same
subset used for every candidate to keep the comparison fair) is run at
BOTH the screening precision and native/BF16 precision, and the quality
delta is measured and recorded. **A material quantization-induced drop
does not, by itself, disqualify a candidate** — Round B's full
revalidation is the authoritative measurement for any candidate that
reaches finalist status. The acceptable quantization-loss threshold
(above which a screening-round result is treated as unreliable rather
than a genuine capability signal) is defined at execution time, using
the calibration subset's own measured variance — this document locks
the requirement to measure and document the delta, not a single
universal numeric threshold, for the same reason §5's tie-region
threshold isn't universal: the right number depends on the actual
suite/precision combination in use.

## 9. What must be locked before any execution begins

Restating the non-negotiable ordering, because it is the single most
important rule in this contract: category scoring types (§1), the judge
escalation rule (§3), hard-gate categories (§4), the tie-region
principle (§5), the common-core config and extension-run boundaries
(§6), the reasoning-track protocol (§7), and the quantization-round
structure (§8) are all fixed by this document, in this phase, before any
candidate's results exist. Any aggregate weighting formula adopted later
must be committed to this repository, and reviewed, **before** it is
applied to real results — never derived from or adjusted in response to
those results.
