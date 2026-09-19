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
- **Conflict handling — LOCKED numeric threshold (Phase 21B.4.9.1)**:
  every rubric, regardless of its native scale, is normalized to `[0,1]`
  before any cross-judge comparison (§5.1 below) — this is what makes a
  single numeric tolerance meaningful across different rubrics/judge
  models chosen later. An item escalates to human adjudication when
  **any** of:
  1. the judges disagree on the item's binary pass/fail classification
     (where the category has one), OR
  2. the judges' normalized scores differ by **more than 0.15** (15
     points on the `[0,1]` scale), OR
  3. either judge flags a potential hard-gate violation (§4;
     `GENESIS_FRONTIER_DECISION_GATES.md` §C), regardless of the other
     judge's score.

  This numeric tolerance (0.15) is chosen now, before any judge model is
  selected or any candidate is judged, specifically so it cannot be
  tuned to make a particular candidate's disagreements look smaller.
  It is deliberately tight relative to the `[0,1]` scale: judge
  agreement within roughly one rubric-grade-band is expected for a
  well-specified rubric, so a gap this large signals a genuine rubric-
  interpretation or capability-assessment disagreement, not ordinary
  scoring noise. Items resolved by agreement (no escalation) use the
  mean of the judges' normalized scores as the task's resolved score
  (§5.1) — never a single judge's score, even when they agree exactly.
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

## 5. Statistical contract (LOCKED — Phase 21B.4.9.1)

Phase 21B.4.9's version of this section left the comparison statistic
as "confidence intervals overlap/don't overlap," which an independent
audit correctly identified as statistically insufficient: two
standalone confidence intervals can overlap while their PAIRED
difference is still significant (and vice versa, in principle), because
overlap comparisons ignore the correlation between paired measurements
on the same tasks. This section replaces that with a single, fully
specified paired-difference framework used everywhere a comparison is
made — frontier gap, control superiority, tie/practical-equivalence,
and quantization regression all use exactly this framework, never a
bespoke variant.

### 5.1 Sampling unit and score normalization

- **The TASK is the sampling unit** — never a judge call. For
  judge-required categories, the ≥2 machine judges' normalized scores
  for a given task are first resolved into ONE task-level score (their
  mean, when they agree within tolerance per §3; the human
  adjudicator's resolved score, when they don't) BEFORE that task
  enters any bootstrap or difference computation. Bootstrapping over
  individual judge calls as if they were independent tasks would
  understate the true sampling variance and is explicitly prohibited.
- **Every category's per-task score is normalized to `[0,1]`** before
  any cross-category or cross-candidate arithmetic: pass/fail becomes
  `1.0`/`0.0`; a judge rubric's native scale (whatever it turns out to
  be once a rubric is finalized) is linearly rescaled to `[0,1]`.

### 5.2 Comparison statistic: paired bootstrap over task IDs

For any category-level comparison between a candidate and a comparator
(a frontier reference, the frontier-reference median, or a control
comparator — §"Frontier comparator" and `GENESIS_FRONTIER_DECISION_GATES.md`
§"Control superiority"), the statistic is:

```
D = candidate_score - comparator_score   (per task, then aggregated)
```

computed via **paired bootstrap over task IDs**, exactly as follows:

1. For the category's full set of shared task IDs (tasks both the
   candidate and the comparator were evaluated on — an unpaired task is
   excluded from this comparison, never imputed), draw a bootstrap
   resample of task IDs, WITH replacement, of the same size as the
   original set.
2. For that resample, compute the candidate's category score (mean of
   its normalized per-task scores over the resampled IDs).
3. Compute the registered comparator's score the same way, over the
   SAME resampled IDs (this is what makes it "paired" — both scores are
   always computed from the identical resampled task set, preserving
   the task-level correlation between candidate and comparator
   performance).
4. Store `D = candidate_score - comparator_score` for this resample.
5. Repeat for **10,000 resamples** (a standard count for stable
   percentile-bootstrap confidence intervals; fixed now so it cannot be
   adjusted later to narrow or widen an inconvenient interval).
6. The 95% confidence interval for `D` is the resample distribution's
   2.5th and 97.5th percentiles (percentile bootstrap method).

**Confidence level: 95%, two-sided, fixed for every comparison in this
contract.** Not adjusted per comparison, per category, or after seeing
results.

### 5.3 Interpreting the interval — never resolve uncertainty in the candidate's favor

Every threshold in this contract (§"Frontier comparator" thresholds,
control-superiority, tie region, quantization regression) is expressed
as a check against the paired-difference confidence interval from §5.2,
using the same three-way outcome pattern:

- **Bound clears the threshold** → the favorable classification applies.
- **Bound clearly fails the threshold** → the unfavorable classification
  applies.
- **Interval straddles the threshold** → **INCONCLUSIVE**, which is
  NEVER treated as a pass. An inconclusive result blocks a frontier-
  class, control-superiority, or non-inferiority claim exactly as
  firmly as a confirmed failure would — the correct response to an
  inconclusive result is more evidence (see §"Sample size" in
  `GENESIS_FRONTIER_EXECUTION_PLAN.md`), never a loosened threshold or a
  favorable default.

### 5.4 Locked numeric margins

All four margins below are `[0,1]`-scale numbers, chosen now — before
any candidate result exists — from general benchmark-methodology
convention (typical LLM-evaluation task-level noise and standard
effect-size practice), not from this project's own candidate data
(there is none yet). They may not be adjusted after seeing results.

| Margin | Value | Used for | Definition |
|---|---|---|---|
| `delta_frontier` | **0.08** | Non-inferiority vs. the frontier-reference median, per critical category | See `GENESIS_FRONTIER_DECISION_GATES.md` §"Frontier gap metric" |
| `delta_best_reference` | **0.20** | Ceiling guard vs. the single strongest reference, per critical category | See `GENESIS_FRONTIER_DECISION_GATES.md` §"Best-reference ceiling guard" |
| `delta_control_superiority` | **0.10** | Substantial-improvement-over-controls check, per critical category | See `GENESIS_FRONTIER_DECISION_GATES.md` §"Control superiority" |
| `delta_tie` | **0.03** | Practical-equivalence region for pairwise finalist comparison | §5.5 below |

**Why these specific values**: `delta_frontier` (8 points) requires
genuine near-parity with frontier capability, not "roughly similar" —
tighter than typical reported benchmark noise floors (often 3-5 points
on well-constructed suites), so a candidate clearing this bound has
cleared a real bar. `delta_best_reference` (20 points) is deliberately
looser — it is a sanity-check ceiling guard, not the primary bar, and
exists only to catch a candidate that is dramatically behind the actual
capability ceiling even while nominally clearing the (possibly lower)
median. `delta_control_superiority` (10 points) requires a gap larger
than `delta_frontier` itself, reflecting that "substantially beats a
much smaller/weaker control" should be an easier bar to clear than
"is statistically indistinguishable from frontier capability."
`delta_tie` (3 points) is deliberately tight — two candidates are only
called practically equivalent when the difference is small enough that
no reasonable foundation decision would treat it as a discriminator.

### 5.5 Tie / practical-equivalence classification — CORRECTED four-way partition (LOCKED, Phase 21B.4.9.2)

For a pairwise finalist comparison `D = A_score - B_score`, using the
same paired-bootstrap framework (§5.2) on the finalists' shared task
IDs, with `delta_tie = 0.03`, let `[lower, upper]` be the 95% CI for
`D`. An independent audit found the prior "meaningfully ahead" wording
mathematically insufficient (it did not fully specify all four possible
interval positions relative to the two threshold lines); the exact
four-way partition, covering every possible interval position with no
gap or overlap, is locked as follows:

- **PRACTICALLY EQUIVALENT**: `lower ≥ -0.03` **AND** `upper ≤ +0.03`
  (the interval lies wholly inside `[-0.03, +0.03]`).
- **A MEANINGFULLY AHEAD**: `lower > +0.03`.
- **B MEANINGFULLY AHEAD**: `upper < -0.03`.
- **INCONCLUSIVE**: every other case (the interval is not wholly inside
  the equivalence band, and does not clear either threshold outright) —
  explicitly **not** the same as a tie, and must never be reported as
  one. A wide interval that happens to include zero, or that overlaps
  but does not clear a threshold, means the comparison lacks the power
  to distinguish the two candidates, not that they have been shown to
  be equivalent.

**Worked examples (locked as the reference cases any implementation
must reproduce exactly):**

| CI for `D` | Classification | Why |
|---|---|---|
| `[+0.04, +0.10]` | A meaningfully ahead | `lower = 0.04 > 0.03` |
| `[-0.10, -0.04]` | B meaningfully ahead | `upper = -0.04 < -0.03` |
| `[+0.01, +0.04]` | INCONCLUSIVE | not wholly inside `[-0.03,+0.03]` (`upper=0.04>0.03`), and `lower=0.01` does not clear `+0.03` |
| `[-0.02, +0.02]` | Practically equivalent | wholly inside `[-0.03,+0.03]` |
| `[-0.05, +0.01]` | INCONCLUSIVE | not wholly inside (`lower=-0.05<-0.03`), and `upper=0.01` does not clear `-0.03` |

### 5.6 No overinterpretation of small samples

A confidence interval computed from too few shared tasks will be wide
almost by construction — this is a correct, honest reflection of
insufficient evidence, not a defect in the method. The response to a
wide interval is never to shrink the reported uncertainty or to fall
back to a bare point estimate; it is to report INCONCLUSIVE (§5.3) and,
if the decision genuinely requires resolving it, gather more paired
task evidence (`GENESIS_FRONTIER_EXECUTION_PLAN.md` §"Sample size /
power / resolution planning").

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

### 6.3 Multimodal scope (LOCKED — Phase 21B.4.9.1)

Closing a gap the prior phase left as an open decision: **unless the
owner explicitly changes it BEFORE candidate execution begins**, the
Genesis foundation selection performed under this methodology is
**TEXT/REASONING-FIRST**. Multimodal capability, if evaluated at all, is
recorded as its own separate extension track (§6.2) with its own
reported score — it is **non-decisional** for the Genesis foundation
result: it never contributes to, blends into, or silently advantages a
candidate's capability matrix, frontier-gap computation, or hard-gate
status. This lock exists specifically so a future execution report
cannot decide, after seeing that one candidate happens to support
vision and score well on it, that multimodal "should count" — that
decision, if ever made, must be made and recorded here, in writing,
before any candidate's text results exist, exactly like every other
locked rule in this contract.

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
- **Track selection for the foundation decision (LOCKED — Phase
  21B.4.9.1, closing a prior ambiguity):** "best supported track" is
  **not** simply whichever track scores highest after results exist —
  that would let a post-hoc choice masquerade as a fair rule. The
  candidate's track used for the foundation capability matrix is its
  **product-intended runtime track**, determined by a pre-declared rule
  applied identically to every candidate, and used ONLY if all of the
  following hold:
  1. the track is reproducibly configurable (a fixed, recordable
     setting — not an opaque server-side default that could silently
     change between calls);
  2. if it is the reasoning-enabled track, its reasoning budget is
     bounded and recorded (never left at the model's own unbounded
     default, which would make cost/latency and even output-length-
     driven scoring artifacts incomparable across candidates);
  3. the same track-selection policy is applied to every candidate in
     the comparison — never "reasoning-enabled for this candidate,
     standard-instruct for that one," chosen after seeing which
     favors which;
  4. cost/latency for BOTH tracks (whichever is used and whichever is
     not) remains separately reported regardless of which one feeds
     the capability matrix.

  The pre-declared default (absent a specific product decision to the
  contrary, which must itself be made and recorded BEFORE candidate
  execution, not during it): use the **reasoning-enabled track** for
  the foundation capability matrix when a candidate supports one (since
  Genesis's actual product runtime is expected to benefit from
  reasoning where available), and the standard-instruct track when it
  does not — this default is itself locked now specifically so no
  execution-time observer can quietly pick whichever track a specific
  candidate happens to score better on.

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

### 8.3 Quantization regression test — LOCKED threshold (Phase 21B.4.9.1)

For any candidate screened below native/BF16 precision, a
representative calibration subset (a fixed, small cross-category
sample, the same subset used for every candidate and REUSED for the
stability check in §8.4, to keep both the comparison and the execution
cost efficient) is run at BOTH the screening precision and native/BF16
precision, and the quality delta is measured using the exact §5.2
paired-bootstrap framework: `D = native_score - quantized_score` per
critical category, over the calibration subset's shared task IDs.

**`delta_quantization = 0.05`** (5 points, `[0,1]` scale) — a Round-A
precision is **CERTIFIED FOR SCREENING**, per critical category, only
if the 95% CI's upper bound on `D` is `≤ 0.05`. If the upper bound
exceeds `0.05`, or the interval is too wide to resolve the question
(INCONCLUSIVE, §5.3), that candidate's Round-A precision is **NOT
CERTIFIED** for that category — this does **not** disqualify the
candidate; it escalates it to a higher-precision screening
configuration for that category (owner spec §13: "never punish a model
for a bad quantizer"). A material quantization-induced drop never
disqualifies a candidate on its own — Round B's full native/BF16
revalidation (§8.2) remains the authoritative measurement for any
candidate that reaches finalist status regardless of what the
Round-A certification found.

`delta_quantization` is set tighter than `delta_frontier` (0.08)
deliberately: a quantization method is expected to preserve capability
much more closely than the bar for "close enough to frontier
capability" — a quantizer failing to clear a 5-point bar against the
SAME model's own native-precision output is a much stronger signal of
a poor-fit quantizer than an 8-point gap between two DIFFERENT models
is a signal of a capability gap.

### 8.4 Repeat / stability policy — LOCKED (Phase 21B.4.9.1)

Temperature-0 sampling does not guarantee bit-for-bit determinism
across GPU kernels, batching, or distributed inference configurations
(owner spec §26/§14). Locked policy, applied identically to every
candidate:

- **Subset**: the same fixed calibration subset used for §8.3's
  quantization regression test (efficiency: one subset serves both
  checks).
- **Repeat count**: **3 repeats** per task, under the identical exact
  model revision, inference config, and hardware class (not merely
  "the same GPU model" loosely — the same qualified compute resource
  configuration) as the original run.
- **Stability metric**: for deterministic/executable tasks, all 3
  repeats must agree on pass/fail. For continuous/rubric-scored tasks,
  all 3 repeats' normalized scores must fall within `delta_tie` (0.03,
  §5.4) of their own mean.
- **Instability threshold and behavior**: a task failing its stability
  metric is marked **UNSTABLE** and excluded from that category's point
  estimate until investigated — never silently averaged in, and never
  resolved by picking the "best" of the 3 repeats (that would be an
  undisclosed best-of-N, prohibited below).
- **Best-of-N is NOT permitted** as a scoring method for any category,
  for any candidate, **unless** best-of-N sampling is an explicit,
  intended part of ORNEUR's actual PRODUCT runtime for Genesis (i.e.
  the deployed product itself will sample N times and select — not
  merely a benchmark-time trick to inflate a score) AND every candidate
  in the comparison receives the identical best-of-N protocol. Absent
  both conditions, single-sample scoring is used for every candidate,
  and a temperature-0 run that varies beyond the instability threshold
  is reported as `UNSTABLE / INCONCLUSIVE`, never resolved by cherry-
  picking the most favorable repeat.

## 9. What must be locked before any execution begins

Restating the non-negotiable ordering, because it is the single most
important rule in this contract: category scoring types (§1), the judge
escalation rule and its numeric disagreement threshold (§3), hard-gate
categories (§4), the full statistical contract including all four
locked margins (§5), the common-core config, extension-run boundaries,
and the multimodal scope lock (§6), the reasoning-track selection
protocol (§7), and the quantization-round structure with its locked
certification threshold and the repeat/stability policy (§8) are all
fixed by this document, in this phase, before any candidate's results
exist. Any aggregate weighting formula adopted later must be committed
to this repository, and reviewed, **before** it is applied to real
results — never derived from or adjusted in response to those results.
