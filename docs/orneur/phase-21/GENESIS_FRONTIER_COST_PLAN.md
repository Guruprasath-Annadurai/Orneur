# Genesis Frontier Cost Plan

**Phase 21B.4.9 — ESTIMATE AND STRATEGY ONLY. Zero spend this phase.**
No compute is reserved, started, or billed by this document. Every
number below is a planning estimate for a future, separately authorized
execution phase.

## 1. ₹0 out-of-pocket strategy

Owner constraint, unchanged across every prior phase: **₹0 owner cash
spend.** The execution phase must draw exclusively from:

- **Modal credits** — the qualified $0-spend-limit workspace
  (`guruprasath-annadurai`, verified live in Phase 21B.4.7A) remains the
  primary trusted-GPU-inference compute source. Current cumulative
  metered spend across all prior phases remains in the low cents, fully
  covered by included credits, $0.00 billed.
- **Race balance / FLOPs** (if applicable to this project's other
  credit sources — carried forward as an available option, not
  otherwise detailed in this document since no qualification work for
  it has occurred in this project to date).
- **Lightning AI credits** — explicitly NOT QUALIFIED as of Phase
  21B.4.5 (account-creation capability boundary; owner action required
  to activate). Available only if the owner separately completes
  qualification before execution begins.
- **Grants / free compute** — any additional free-tier resource the
  owner identifies and authorizes before execution.

**No spend is authorized by this phase.** The estimates below exist so
a future execution-authorization decision is made with real cost
awareness, not to justify starting any run now.

## 2. Cost estimation must happen before launch, not after

Every execution stage (`GENESIS_FRONTIER_EXECUTION_PLAN.md`) must have
its expected cost estimated BEFORE that stage begins, using: the
number of candidates entering the stage, the number of tasks each will
run, the model size/precision (hence GPU-time per task), and the
qualified compute resource's actual rate card. A stage that would
exceed a pre-set credit ceiling is not silently allowed to proceed
past it — this mirrors the per-phase credit-ceiling discipline already
established (e.g. Phase 21B.4.8.1's $0.50 vLLM-qualification ceiling).

**Quality is never lowered to save credits.** If a genuinely necessary
evaluation exceeds available credit, the correct response is to defer
that specific run (or seek additional authorized credit) — never to
substitute a cheaper-but-worse evaluation and represent it as
equivalent evidence.

## 3. Expected screening cost (Stage 1-3, Round A) — CORRECTED per-candidate (Phase 21B.4.9.1)

**Correction note:** the prior version of this section said deployable
candidates "fit Modal L4 ... at appropriate quantization" as a blanket
statement. An independent audit correctly identified that this
oversimplifies: `GENESIS_FRONTIER_COMPUTE_MATRIX.md`'s own weight-
storage table (computed from TOTAL parameters, never active parameters
— Mistral Small 4's 119B TOTAL / ~6.5B active is the explicit example
the audit raised) shows most of the deployable pool does **not** fit a
single L4 (24GB) even at aggressive quantization. This section replaces
the blanket claim with a candidate-specific envelope for every
deployable candidate and control, distinguishing THEORETICAL MINIMUM
weight storage from a PRACTICAL inference configuration (which must add
quantization metadata, KV cache, runtime workspace, and — per
`GENESIS_FRONTIER_COMPUTE_MATRIX.md`'s existing 20-40%+ headroom rule of
thumb — real serving margin on top of the theoretical floor).

### 3.1 Per-candidate compute envelope (L4 = 24GB; theoretical weight-storage GPU count against L4 specifically, not the 80GB-class figures already tabulated in `GENESIS_FRONTIER_COMPUTE_MATRIX.md`)

| Candidate | Total params | Active params (NOT the storage driver) | BF16 weight bytes | FP8 weight bytes | INT4 weight bytes | Fits single L4 (24GB) at any precision? |
|---|---|---|---|---|---|---|
| Qwen3.8-27B (dense) | 27B | 27B (dense — all params active) | 54GB → 3×L4 | 27GB → **2×L4** (exceeds 24GB alone) | 14GB → **1×L4 (fits)** | **Yes, INT4 only** |
| Qwen3.8-Flash-Next (full, ~180B — the correct figure per `GENESIS_FRONTIER_COMPUTE_MATRIX.md`, never the smaller 125B core-only figure) | 180B | 6B core-MoE active | 360GB → 15×L4 | 180GB → 8×L4 | 90GB → 4×L4 | **No, at any precision tabulated** |
| Mistral Small 4 | 119B | ~6.5B | 238GB → 10×L4 | 119GB → 5×L4 | 60GB → 3×L4 | **No, at any precision tabulated** |
| GLM-5.3-Flash | 320B | (MoE, active count not separately re-verified this phase) | 640GB → 27×L4 | 320GB → 14×L4 | 160GB → 7×L4 | **No, at any precision tabulated** |
| Qwen3-8B (control) | 8B | 8B (dense) | 16GB → **1×L4 (fits)** | 8GB → 1×L4 | 4GB → 1×L4 | **Yes, BF16/FP8/INT4 all fit** |
| Mistral-Nemo-Instruct-2407 (control) | 12B | 12B (dense) | 24GB → borderline 1×L4 (no headroom for KV cache/workspace at BF16) | 12GB → 1×L4 | 6GB → 1×L4 | **Yes, FP8/INT4 comfortably; BF16 only with no serving headroom** |
| Phi-4 (control) | 14B | 14B (dense) | 28GB → 2×L4 | 14GB → 1×L4 | 7GB → 1×L4 | **Yes, FP8/INT4** |

**Corrected conclusion:** of the four deployable candidates, only
**Qwen3.8-27B** fits a single L4 GPU, and only at INT4 precision (the
theoretical 27GB FP8 figure alone already exceeds L4's 24GB, before any
KV-cache/runtime-workspace overhead is added). Qwen3.8-Flash-Next,
Mistral Small 4, and GLM-5.3-Flash all require **multi-GPU** (or a
larger single-GPU class, e.g. 80GB-class per `GENESIS_FRONTIER_COMPUTE_MATRIX.md`'s
existing table) at every tabulated precision — this is stated plainly so
no execution report can implicitly assume single-L4 screening was ever
uniformly viable across the deployable pool. All three controls fit a
single L4 comfortably at FP8/INT4.

**Theoretical vs. practical, restated for this table specifically:** the
byte figures above are the weight-storage FLOOR only. A PRACTICAL
Round-A screening configuration for any candidate in this table must add
`GENESIS_FRONTIER_COMPUTE_MATRIX.md`'s already-documented overhead
(quantization metadata, KV cache, runtime workspace, 20-40%+ headroom
rule of thumb) — meaning even Qwen3.8-27B's "fits 1×L4 at INT4" result
has little to no serving headroom left over, and should be treated as a
tight fit requiring careful KV-cache/context-length budgeting, not a
comfortable margin.

### 3.2 Candidate-specific cost envelope (Round-A screening, Modal rates from `GENESIS_FRONTIER_COMPUTE_MATRIX.md`'s live rate card)

Per-candidate estimates, NOT a blanket "low dollars per candidate"
figure. Exact live prices are to be reverified in Phase 21B.4.10, not
assumed frozen from this phase's research:

| Candidate | GPU class (practical, incl. headroom) | GPU count | Rate/hr (per GPU) | Est. load+90-task Tier-1 runtime | Est. cost envelope |
|---|---|---|---|---|---|
| Qwen3.8-27B | L4 (INT4) | 1 | $0.80 | ~20-40 min (model load + 90 short-context generations) | **~$0.30-0.55** |
| Qwen3.8-Flash-Next | A100-80GB or similar (FP8, 2× per the 80GB-class table) | 2 | $2.50 | ~30-60 min | **~$2.50-5.00** |
| Mistral Small 4 | A100-80GB (FP8, 2× per the 80GB-class table) | 2 | $2.50 | ~30-60 min | **~$2.50-5.00** |
| GLM-5.3-Flash | A100-80GB (INT4, 7× per the 80GB-class table — the cheapest tabulated precision still needs 7 GPUs at this size) | 7 | $2.50 | ~30-60 min | **~$8.75-17.50** |
| Qwen3-8B (control) | L4 | 1 | $0.80 | ~15-30 min | **~$0.20-0.40** |
| Mistral-Nemo-Instruct-2407 (control) | L4 | 1 | $0.80 | ~15-30 min | **~$0.20-0.40** |
| Phi-4 (control) | L4 | 1 | $0.80 | ~15-30 min | **~$0.20-0.40** |

These are order-of-magnitude planning estimates built from
`GENESIS_FRONTIER_COMPUTE_MATRIX.md`'s existing live rate card and
Phase 21B.4.8.1's own small-model load/generate timing evidence,
extrapolated (not re-measured) to larger models' longer expected load
times — no compute was started this phase to verify them. GLM-5.3-Flash
is notably the most expensive deployable candidate to screen even at
its cheapest tabulated precision, a direct consequence of its 320B
total-parameter footprint; this is recorded plainly rather than
smoothed into an average that would hide it.

- **Frontier reference models** (DeepSeek V4.1-Flash, GLM-5.3 flagship,
  Mistral Large 3, MiniMax M3, Qwen3.8-Max, Kimi K3) are, per
  `GENESIS_FRONTIER_COMPUTE_MATRIX.md`, largely compute-prohibitive to
  self-host even at Round-A precision (each requires 8-70 GPUs at the
  80GB class, per that document's table). The methodology's answer (owner
  spec §33's "use hosted references when loading flagship weights is
  irrational") is to evaluate these via their own hosted/managed API
  endpoints where available (§6 below governs exactly when this is
  permitted under the ₹0 constraint), recording the exact provider-
  returned model identifier and call metadata per
  `GENESIS_FRONTIER_HOLDOUT_SPEC.md`'s mutable-API-model policy. Exact
  provider/pricing research for hosted access is NOT performed in this
  phase.

## 4. Expected finalist cost (Stage 4-7) — CORRECTED for the removed cost-based elimination (Phase 21B.4.9.1)

**Correction note:** Stage 4's promotion gate no longer reduces the
candidate count for cost reasons (`GENESIS_FRONTIER_EXECUTION_PLAN.md`'s
corrected Stage 3→4 rule) — every eligible candidate, reference, and
control required by a registered comparator is entitled to Stage 4/6
execution, deferred (`DEFERRED_FOR_COMPUTE`) rather than eliminated if
credits are temporarily short. This section's cost reasoning is updated
accordingly: the FULL eligible pool's Stage 4/6 cost must be planned
for, even though it may need to be spread across multiple credit
cycles (§1) rather than executed in one pass.

- **Stage 4 (sealed holdout)** covers every candidate/reference/control
  that survives Stage 0-3 with no confirmed hard-gate failure — using
  the candidate-specific envelopes in §3.1-3.2 (scaled up for the
  private holdout's expected harder/potentially-longer-context tasks,
  which this phase does not author and therefore cannot cost exactly).
  If the full pool's Stage 4 cost exceeds what a single credit cycle can
  cover, execution is spread across cycles (§1's Modal-credits-renew-
  monthly reality) — deferred, never eliminated.
- **Stage 6 (Round B, native/BF16 finalist revalidation)** costs more
  per task than Round A (higher precision means more VRAM and often
  slower throughput) and now, per the corrected promotion rule, applies
  to every candidate that is frontier-non-inferior, INCONCLUSIVE, or
  quantization-suspect — potentially a larger set than "only the
  clearest winners," since INCONCLUSIVE results are not resolved
  downward to avoid this cost.
- **Judge calls (Stage 5)** — at minimum two independent machine judges
  per judge-required item across the full Stage-4-completing pool; cost
  scales with (candidate count) × (judge-required task count) × (2+
  judges) × (judge model's per-token rate). This is the category most
  sensitive to which judge models are eventually selected (not decided
  this phase) — exact cost estimation is deferred to that selection.

## 5. Hosted frontier reference cost — zero-cash rule (LOCKED, owner spec §21)

**Do not assume hosted APIs are cheap enough or free enough merely
because per-token pricing looks small relative to self-hosting.** The
owner's ₹0 cash constraint applies to hosted-reference execution
exactly as strictly as it applies to GPU compute:

- A hosted frontier reference (via Modal's pay-per-token Shared
  Endpoints, per `GENESIS_FRONTIER_COMPUTE_MATRIX.md`'s "Practical
  implication" section, or any other provider) may be executed **only
  when** free credits, promotional quota, a research allocation, or
  another explicitly zero-cash access path covers the run.
- **If no zero-cash path covers it:** the reference's execution status
  is `REFERENCE EXECUTION = DEFERRED` — recorded exactly like a
  `DEFERRED_FOR_COMPUTE` candidate — never silently paid for out of
  owner cash.
- **The frontier reference set is never weakened merely to fit current
  credits** (e.g. quietly dropping an expensive-to-access reference from
  the registered set because a cheaper one is available) without
  recording the consequence explicitly as a `REFERENCE_UNAVAILABLE`
  entry and the corresponding reduced-reference-set flag
  (`GENESIS_FRONTIER_DECISION_GATES.md` §"Frontier reference set") — a
  silent, cost-driven weakening of the comparator set would reintroduce
  exactly the kind of credit-driven capability distortion this phase
  exists to close for candidates.

## 6. Screen cheaply, reserve expensive runs for finalists (funnel-level cost lever, CORRECTED)

Restating the funnel's cost discipline, corrected for the removed
cost-based elimination: the funnel's cost efficiency now comes from
**staging fidelity**, not from **shrinking the eligible pool**. Stage 0
is the only boundary that removes a candidate from the pool on
non-capability, non-deferrable grounds (license/identity/runtime
ineligibility); every other boundary either resolves already-collected
evidence (Stage 2→3, 4→5) or increases per-candidate fidelity for
candidates that have earned it through cheaper evidence, while
DEFERRING (never eliminating) any candidate the current credit cycle
cannot yet afford to advance. No stage runs the full eligible pool at
the MOST expensive precision/protocol simultaneously — the sequencing
(cheap screening first, expensive revalidation reserved for candidates
that need it) is what keeps this affordable, not a reduction in how
many candidates ultimately receive the decisive benchmark.

## 7. Owner cash spent this phase

**$0.00.** No compute reserved, started, or billed. No account created.
No credit consumed. This document is planning only.

## 8. Expected result of this phase's cost accounting

**$0 / ₹0** — matching every prior phase's discipline. The estimates in
§3-4 exist to inform the owner's future execution-authorization
decision with realistic cost awareness, not to pre-approve any spend.
