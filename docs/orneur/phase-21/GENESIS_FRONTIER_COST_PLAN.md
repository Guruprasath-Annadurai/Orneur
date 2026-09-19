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

### 3.1 Per-candidate compute envelope — CORRECTED (Phase 21B.4.9.2): theoretical weight-storage math is NOT a practical topology claim

**Correction note:** the prior version of this table computed a
"practical GPU count" purely by dividing theoretical weight bytes by a
GPU's VRAM (`ceil(weight_GB / GPU_VRAM_GB)`) and, in two cases, even got
that arithmetic wrong by carrying over the wrong precision column. An
independent audit correctly rejected both the arithmetic errors and the
underlying method: dividing weight bytes by VRAM gives only a
THEORETICAL MINIMUM — it says nothing about whether a real inference
runtime can actually shard that model across that many GPUs, whether
enough VRAM remains for KV cache/workspace once the weights are loaded,
or whether the architecture's own tensor/expert-parallelism support
covers that GPU count at all. Every candidate row below now carries TWO
explicitly separate fields: **MINIMUM THEORETICAL GPU COUNT** (weight
bytes only, arithmetic floor) and **QUALIFIED PRACTICAL GPU TOPOLOGY**
(real runtime evidence) — the latter is `UNQUALIFIED / TBD` for every
candidate until a future phase actually qualifies it against live
runtime/architecture support, exactly as Phase 21B.4.8.1/.2 qualified
vLLM on a real Modal L4 GPU before claiming it worked.

| Candidate | Total params | BF16 floor | FP8 floor | INT4 floor | MINIMUM THEORETICAL GPU count (80GB-class, from `GENESIS_FRONTIER_COMPUTE_MATRIX.md`'s own table — the authoritative source; L4-derived counts are NOT interchanged with this column) | QUALIFIED PRACTICAL GPU TOPOLOGY |
|---|---|---|---|---|---|---|
| Qwen3.8-27B (dense) | 27B | 54GB | 27GB | 14GB | BF16: 1×; FP8: 1×; INT4: 1× | `UNQUALIFIED / TBD` — plausible at 1×L4 (24GB) for INT4 given the 14GB floor, but load + KV/workspace overhead is not yet qualified live; **QUALIFICATION REQUIRED** before treating 1×L4 as practical |
| Qwen3.8-Flash-Next (full, ~180B — the correct total figure, never the smaller 125B core-only figure) | 180B | BF16: 360GB → 5× | FP8: 180GB → **3×** (CORRECTED — 2×80GB=160GB is physically insufficient even for weights alone; the prior version's "2×" was an error) | INT4: 90GB → 2× | 5× / 3× / 2× (BF16/FP8/INT4 respectively) | `UNQUALIFIED / TBD` — even the corrected 3× FP8 minimum leaves only 60GB of headroom above the 180GB weight floor across 3 GPUs combined, which architecture/runtime parallelism support has not been qualified against |
| Mistral Small 4 (119B total / ~6.5B active — active parameters are explicitly NOT the storage driver) | 119B | BF16: 238GB → 3× | FP8: 119GB → 2× | INT4: 60GB → 1× | 3× / 2× / 1× | `UNQUALIFIED / TBD` — 2×80GB (FP8) provides theoretical capacity with zero measured margin for runtime/KV/workspace overhead; **QUALIFICATION REQUIRED** |
| GLM-5.3-Flash | 320B | BF16: 640GB → 8× | FP8: 320GB → 4× | INT4: 160GB → **2×** (CORRECTED — the prior version's "7×" was an erroneous carry-over from the L4-count calculation, not this 80GB-class column) | 8× / 4× / 2× | `UNQUALIFIED / TBD` — the corrected 2× INT4 minimum gives EXACTLY 160GB against a 160GB floor, i.e. ZERO runtime headroom; this is very unlikely to be practically viable at exactly 2 GPUs, and the actual practical count (likely 3+) is not yet qualified |
| Qwen3-8B (control) | 8B | 16GB | 8GB | 4GB | 1× at every precision (80GB-class) | `UNQUALIFIED / TBD` for L4-class specifically, though plausible given ample headroom at any precision |
| Mistral-Nemo-Instruct-2407 (control) | 12B | 24GB | 12GB | 6GB | 1× at every precision (80GB-class) | `UNQUALIFIED / TBD` — BF16's 24GB floor leaves no L4-class headroom; FP8/INT4 more plausible pending qualification |
| Phi-4 (control) | 14B | 28GB → 2× | 14GB → 1× | 7GB → 1× | 2× (BF16) / 1× (FP8, INT4) | `UNQUALIFIED / TBD` |

**Do not read the "MINIMUM THEORETICAL GPU count" column as a
deployment recommendation.** It is exactly what its name says: a floor
computed from weight bytes alone. The "QUALIFIED PRACTICAL GPU
TOPOLOGY" column is the one that matters for actually running
anything, and it is `UNQUALIFIED / TBD` for every single candidate in
this table as of this phase — Phase 21B.4.10 is where that
qualification work belongs (§3.2 below).

### 3.2 Candidate-specific cost envelope — PRELIMINARY, NOT EXECUTION-AUTHORIZED (Phase 21B.4.9.2)

**Every dollar figure below is marked `PRELIMINARY / NOT
EXECUTION-AUTHORIZED`** because it is derived from a GPU topology that
is itself `UNQUALIFIED / TBD` (§3.1) — an independent audit correctly
identified that retaining false precision (e.g. "$2.50-$5.00") for a
candidate whose actual GPU count and runtime behavior have not been
qualified would misrepresent planning-stage arithmetic as an executable
budget. These figures exist only to give the owner order-of-magnitude
awareness before Phase 21B.4.10's live requalification — they are NOT a
number Phase 21B.4.10 or any later phase may treat as a pre-approved
spend ceiling.

| Candidate | Illustrative GPU class × count (theoretical floor, NOT qualified) | Rate/hr (per GPU, from the existing live rate card — subject to reverification) | Illustrative runtime | Cost figure |
|---|---|---|---|---|
| Qwen3.8-27B | 1× L4 (INT4, theoretical) | $0.80 | ~20-40 min | `PRELIMINARY / NOT EXECUTION-AUTHORIZED` — illustrative range ~$0.30-0.55 |
| Qwen3.8-Flash-Next | 3× A100-80GB (FP8, corrected theoretical floor) | $2.50 | ~30-60 min | `PRELIMINARY / NOT EXECUTION-AUTHORIZED` — illustrative range ~$3.75-7.50 |
| Mistral Small 4 | 2× A100-80GB (FP8, theoretical floor) | $2.50 | ~30-60 min | `PRELIMINARY / NOT EXECUTION-AUTHORIZED` — illustrative range ~$2.50-5.00 |
| GLM-5.3-Flash | 2× A100-80GB (INT4, corrected theoretical floor — zero headroom, likely not the real practical count) | $2.50 | ~30-60 min | `PRELIMINARY / NOT EXECUTION-AUTHORIZED` — illustrative range ~$2.50-5.00 AT THE THEORETICAL FLOOR ONLY; the real practical count is expected higher once qualified, and this figure should not be quoted without that caveat |
| Qwen3-8B (control) | 1× L4 | $0.80 | ~15-30 min | `PRELIMINARY / NOT EXECUTION-AUTHORIZED` — illustrative range ~$0.20-0.40 |
| Mistral-Nemo-Instruct-2407 (control) | 1× L4 | $0.80 | ~15-30 min | `PRELIMINARY / NOT EXECUTION-AUTHORIZED` — illustrative range ~$0.20-0.40 |
| Phi-4 (control) | 1× L4 | $0.80 | ~15-30 min | `PRELIMINARY / NOT EXECUTION-AUTHORIZED` — illustrative range ~$0.20-0.40 |

**Phase 21B.4.10 must reverify, live, before any executable credit
envelope may be locked:**
- current Modal GPU inventory;
- current rates (this phase's rate card may have changed);
- supported GPU counts for multi-GPU tensor/expert-parallel Functions;
- architecture/runtime compatibility for each candidate's actual model
  class (MoE routing, custom attention, etc.);
- quantized-checkpoint support (whether a suitable pre-quantized
  checkpoint exists, or ORNEUR must quantize one itself, which is a
  materially different cost/complexity profile); and
- the practical load topology (GPU count, parallelism strategy) that
  actually works for each candidate, replacing every `UNQUALIFIED / TBD`
  entry in §3.1 with a real, live-tested value.

Only after that reverification may an executable credit envelope be
locked. Owner cash remains **₹0** throughout.

- **Frontier reference models** (DeepSeek V4.1-Flash, GLM-5.3 flagship,
  Mistral Large 3, MiniMax M3, Qwen3.8-Max, Kimi K3) are, per
  `GENESIS_FRONTIER_COMPUTE_MATRIX.md`, largely compute-prohibitive to
  self-host even at Round-A precision (each requires 8-70 GPUs at the
  80GB class, per that document's table — itself a theoretical-floor
  figure, subject to the same practical-qualification caveat as §3.1).
  The methodology's answer (owner spec §33's "use hosted references
  when loading flagship weights is irrational") is to evaluate these
  via their own hosted/managed API endpoints where available (§5 below
  governs exactly when this is permitted under the ₹0 constraint),
  recording the exact provider-returned model identifier and call
  metadata per `GENESIS_FRONTIER_HOLDOUT_SPEC.md`'s mutable-API-model
  policy. Exact provider/pricing research for hosted access is NOT
  performed in this phase.

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
