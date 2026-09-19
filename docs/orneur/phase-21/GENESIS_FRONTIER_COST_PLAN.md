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

## 3. Expected screening cost (Stage 1-3, Round A)

Rough order-of-magnitude reasoning, not a committed budget:

- **Deployable candidates** (Qwen3.8-27B, Qwen3.8-Flash-Next, Mistral
  Small 4 119B-A6.5B, GLM-5.3-Flash) and **controls** (Qwen3-8B,
  Mistral-Nemo-Instruct-2407, Phi-4) are the realistic Round-A execution
  pool — these fit Modal L4 (or better, if available within the $0
  ceiling) at appropriate quantization per
  `GENESIS_FRONTIER_SCORING_CONTRACT.md` §8.1.
- Per Phase 21B.4.8.1's own vLLM qualification evidence, a small model's
  full inference cycle (load + generate) on Modal L4 costs low single-
  digit cents of metered compute; a 90-task Tier-1 run per candidate,
  even accounting for larger deployable-class models needing longer
  load/generation time, is expected to remain in the **low dollars per
  candidate** range at Round-A screening precision — well within a
  $0-billed Modal Starter workspace's included credit, based on the
  `modal billing rates`/`modal billing summary` evidence already
  gathered.
- **Frontier reference models** (DeepSeek V4.1-Flash, GLM flagship,
  Mistral Large 3, MiniMax M3, Qwen3.8 flagship/Max, Kimi K3) are, per
  `GENESIS_FRONTIER_COMPUTE_MATRIX.md`, largely compute-prohibitive to
  self-host even at Round-A precision. The methodology's answer (owner
  spec §33's "use hosted references when loading flagship weights is
  irrational") is to evaluate these via their own hosted/managed API
  endpoints where available, recording the exact provider-returned
  model identifier and call metadata per `GENESIS_FRONTIER_HOLDOUT_SPEC.md`'s
  mutable-API-model policy — this converts a large self-hosting cost
  into a per-token API cost, which is dramatically smaller for a
  90-task-plus-holdout evaluation volume. Exact provider/pricing
  research for this is NOT performed in this phase.

## 4. Expected finalist cost (Stage 4-7)

- **Stage 4 (sealed holdout)** is deliberately reserved for a small,
  cost-efficiency-gated subset of candidates (`GENESIS_FRONTIER_EXECUTION_PLAN.md`
  Stage 3→4 gate) — expected volume is a fraction of the full Tier-1
  screening volume, keeping this stage's cost proportionally small even
  though individual holdout tasks may be more expensive to construct
  and run (harder, potentially longer-context prompts).
- **Stage 6 (Round B, native/BF16 finalist revalidation)** costs more
  per task than Round A (higher precision means more VRAM and often
  slower throughput) but again applies only to the small finalist set,
  not the full candidate pool — this is the entire point of the two-
  round design (`GENESIS_FRONTIER_SCORING_CONTRACT.md` §8.2): screen
  cheaply, reserve expensive runs for finalists.
- **Judge calls (Stage 5)** — at minimum two independent machine judges
  per judge-required item across the finalist pool; cost scales with
  (finalist count) × (judge-required task count) × (2+ judges) × (judge
  model's per-token rate). This is the category most sensitive to which
  judge models are eventually selected (not decided this phase) — exact
  cost estimation is deferred to that selection.

## 5. Screen cheaply, reserve expensive runs for finalists

Restating the funnel's cost discipline explicitly, since it is the
primary lever that keeps this evaluation affordable at $0 owner spend:
every stage boundary in `GENESIS_FRONTIER_EXECUTION_PLAN.md` either
reduces the active candidate count (Stage 0, Stage 3→4, Stage 5→6) or
increases per-candidate fidelity only for the candidates that have
already earned it through cheaper evidence. No stage runs the FULL
candidate pool at the MOST expensive precision/protocol simultaneously.

## 6. Owner cash spent this phase

**$0.00.** No compute reserved, started, or billed. No account created.
No credit consumed. This document is planning only.

## 7. Expected result of this phase's cost accounting

**$0 / ₹0** — matching every prior phase's discipline. The estimates in
§3-4 exist to inform the owner's future execution-authorization
decision with realistic cost awareness, not to pre-approve any spend.
