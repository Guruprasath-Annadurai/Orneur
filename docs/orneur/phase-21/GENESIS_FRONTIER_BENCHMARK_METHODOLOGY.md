# Genesis Frontier Benchmark Methodology

**Phase 21B.4.9 — METHODOLOGY DESIGN ONLY.** No candidate is downloaded,
executed, ranked, or selected by this document. No model evaluation,
`genesis-eval-v1` execution/freeze, private holdout authoring, or
Genesis training occurs in this phase. This document defines the RULES
that a future, separately-authorized execution phase must follow.

## 1. The question this methodology answers

> Which foundation strategy gives Genesis the strongest realistic path
> to **frontier-class intelligence** while remaining trainable,
> controllable, deployable, and scalable toward **10,000 real-time
> users**, with no material compromise in intelligence quality?

This is explicitly **not** "which model gets the highest aggregate
score." A single number cannot answer the real question, because the
real question has at least four independent axes that must never be
silently merged:

| Axis | What it measures | What it must NOT be confused with |
|---|---|---|
| **Raw capability** | What the model can do today, unmodified | How cheap it is to run |
| **Deployability** | Whether ORNEUR can actually serve it at scale | How capable it is |
| **Post-training potential** | How much a deployable model could improve via LoRA/QLoRA/distillation/RLHF | Its current raw score |
| **Serving economics** | Cost/latency/infrastructure at 10K users | Intelligence quality |

Every downstream document in this methodology keeps these four axes
reported separately. See `GENESIS_FRONTIER_DECISION_GATES.md` §A-F for
the decision rubric built on top of them.

## 2. Candidate classes

Three distinct classes are maintained throughout. Collapsing them into
one leaderboard is explicitly prohibited — a reference model's score is
not a deployability claim, and a control baseline's score is not an
intelligence ceiling.

### A. Frontier reference models (capability ceiling, not necessarily deployable)

From the locked landscape research (`GENESIS_FRONTIER_MODEL_LANDSCAPE_2026_09.md`):
DeepSeek V4.1-Flash, GLM-5.2/5.3 flagship, Mistral Large 3, MiniMax M3,
the Qwen3.8 flagship/Max reference, Kimi K3. Role: establish the
contemporary capability ceiling ORNEUR is being measured against. These
may be evaluated via hosted/managed APIs where loading the full weights
is infrastructurally irrational (see `GENESIS_FRONTIER_COMPUTE_MATRIX.md`).
**Reference use does not imply teacher/distillation-rights permission**
— that is a separate license question, tracked per-candidate in
`GENESIS_FRONTIER_DECISION_GATES.md` §D and `GENESIS_TEACHER_STUDENT_STRATEGY.md`.

### B. Deployable Genesis foundation candidates

Current pool, unchanged from the locked landscape documents unless a
factual correction is documented: Qwen3.8-27B, Qwen3.8-Flash-Next,
Mistral Small 4 (119B-A6.5B), GLM-5.3-Flash. Every entry in this pool
carries the explicit marker `FRONTIER STATUS: UNPROVEN BY ORNEUR` until
this methodology's execution phase produces first-party evidence.
Adding or removing a candidate from this pool requires a documented
reason (a factual license/architecture correction, not a preference).

### C. Control / small baselines

Qwen3-8B, Mistral-Nemo-Instruct-2407, Phi-4 (Phase 21B.3 shortlist,
reclassified in Phase 21B.4.8). Role: quantify how much capability
class B actually buys over the infrastructure ORNEUR already has
working experience with. **Controls never define the intelligence
target** — they exist only as a lower reference point on the hardness
bands (§4).

## 3. Two-tier benchmark structure

### Tier 1 — `genesis-eval-v1` (public)

90 tasks across the 17 categories below (`orca/eval/genesis_suite.py`).
Purpose: deterministic regression, pipeline continuity, historical
comparison across every phase this project has run. Remains versioned
and immutable after the first real baseline freezes it
(`orca.eval.baseline.record_baseline_and_freeze_suite()`, hardened
through Phase 21B.4.8.3). **Not** the frontier-discrimination
instrument — a suite committed to a public GitHub repository cannot
simultaneously be a secret discrimination benchmark (see
`GENESIS_FRONTIER_HOLDOUT_SPEC.md`'s contamination argument, unchanged
this phase).

### Tier 2 — `genesis-frontier-holdout-v1` (private, specification only)

Purpose: sealed frontier discrimination, harder reasoning, reduced
contamination/benchmark-gaming risk, and finalist differentiation once
strong candidates cluster near the top of Tier 1. This phase extends
the Phase 21B.4.8.1 specification (`GENESIS_FRONTIER_HOLDOUT_SPEC.md`)
with the category/hardness/scoring requirements below, but **authors no
private task content** — that remains separately authorized future
work, consistent with the owner's explicit instruction not to rush
task authoring.

Contamination posture recording is unchanged in mechanism (revision
timestamp vs. holdout creation timestamp, `POST-REVISION HOLDOUT`
marking) and is restated precisely in
`GENESIS_FRONTIER_EXECUTION_PLAN.md` §25.

## 4. Category framework and hardness calibration

Reviewing the current 17 categories against frontier-discrimination
needs:

| # | Category | Current scoring type | Tier-1 status | Tier-2 (frontier holdout) need |
|---|---|---|---|---|
| 1 | General reasoning (wrapped legacy suite) | mixed/deterministic | Sufficient as regression | Harder variant needed — legacy suite was not designed for frontier discrimination |
| 2 | Professional reasoning | LLM-judge | Sufficient | Harder rubric-scored variant, higher ambiguity |
| 3 | Quantitative reasoning | exact match | Sufficient at control/strong band | **Frontier/extreme band required** — current tasks saturate at strong-model level |
| 4 | Coding (unit tests) | executable | Sufficient for toy functions | Needs multi-file/repository tier (§7 below, §22 of the owner's spec) |
| 5 | Debugging | executable | Sufficient | Needs harder, multi-defect repro cases |
| 6 | Software architecture | LLM-judge | Sufficient | Needs system-design-scale prompts |
| 7 | Multi-file reasoning | executable/structural | Present but shallow | **Repository-scale** reasoning is the real gap — see §5 |
| 8 | Requirements interpretation | LLM-judge | Sufficient | Needs deliberately underspecified/ambiguous specs |
| 9 | Product-building reasoning | structured fixture | Sufficient | Adequate as-is |
| 10 | Verification / fabricated-completion resistance | deterministic | Sufficient | Critical category — extend to agentic multi-step claims (§6) |
| 11 | Tool planning | structured schema | Sufficient at basic level | Needs multi-tool, dependency-aware sequencing (§6) |
| 12 | Uncertainty / epistemic behavior | deterministic pattern | Sufficient | Adequate as-is |
| 13 | Capability-expansion reflex (ASI Protocol) | LLM-judge | Sufficient | **Hard-gate category** — see `GENESIS_FRONTIER_DECISION_GATES.md` §C |
| 14 | Human-sovereignty / authority boundaries | deterministic | Sufficient | **Hard-gate category** |
| 15 | Security / adversarial behavior | deterministic pattern | Sufficient | **Hard-gate category** |
| 16 | Model-society interchange | structured fixture | Sufficient | Adequate as-is |
| 17 | Presence Mode / verified task-state | deterministic | Sufficient | Adequate as-is |

New coverage this methodology adds as explicit tracks rather than new
numbered categories (to avoid renumbering the locked Tier-1 suite):

- **Long-context synthesis** (§5.1) — a track, not a category, evaluated
  at multiple context sizes.
- **Agentic/tool-runtime planning depth** (§5.2) — extends category 11's
  frontier-holdout variant.
- **Multimodal** (§5.3) — a fully separate track, included only if
  Genesis v1's actual product role requires it (decision deferred to
  the execution-authorization turn, not assumed here).

Categories NOT added: no marketing-only categories, no categories
duplicating existing coverage under a new name. Every category maps to
a capability ORNEUR's own product roadmap actually needs (agent
orchestration, code generation, tool use, authority discipline) — none
were added to make the suite look more complete than it is.

### 4.1 Hardness bands

Every category's Tier-1 tasks stay at **basic/control** and **strong**
difficulty (per the existing `difficulty` field on `EvalTask`). Tier-2
holdout tasks target **frontier** and **extreme** bands specifically,
so control baselines are expected to score near-floor and true frontier
references are expected to score meaningfully above deployable
candidates on at least some categories — a benchmark where all strong
models cluster at 95-100% cannot discriminate a foundation decision and
is treated as a design defect, not a "good score."

No band is built from artificial trick questions (garden-path phrasing,
adversarial formatting unrelated to the capability under test, etc.) —
every task, regardless of band, measures a capability ORNEUR's product
will actually exercise.

## 5. Additional discrimination dimensions

### 5.1 Long-context synthesis

Advertised context window is not evidence (owner spec §20). The
execution-phase methodology (not run this phase) must test:
retrieval-at-depth (a fact placed at varying document depths),
multi-document synthesis (contradictory sources, requiring the model to
notice and resolve the contradiction), instruction persistence across a
long context (does an early system instruction survive to the end of
generation), and repository-scale reasoning (reusing the multi-file
category's harder variant at full-repository scale). Run at **multiple**
context sizes (not just the maximum advertised), so a model that
degrades gracefully is distinguished from one that only works at
small-context sizes it was actually tuned on.

### 5.2 Agentic / tool-use planning

Separates **planning quality** (can the model select the right tool,
sequence dependent calls correctly, track state across calls, recover
from a simulated tool failure, and refuse to fabricate a tool's result)
from **tool-runtime reliability** (whether an actual external action
executes correctly) — this methodology, and the execution phase it
authorizes, evaluates planning quality only; no external actions are
executed during benchmark design or scoring. State-machine / plan-
contract validation (checking a structured plan against required
preconditions/postconditions, not natural-language judgment) is
preferred wherever the task's plan structure is well-defined enough to
support it — see `GENESIS_FRONTIER_SCORING_CONTRACT.md` §3.

### 5.3 Multimodal

Explicitly deferred as an open decision, not assumed either way:
Genesis's product role may require multimodality later, but this
methodology does not silently reward vision capability if Genesis v1's
actual scope is text-only. **If** a future execution-authorization turn
decides multimodal capability belongs in foundation selection, it runs
as a fully separate track with its own reported score — never blended
into the text capability score, and never given implicit weight by
simply being present.

## 6. Code evaluation

Generated-code execution uses `DockerSandboxBackend` exclusively
(`orca/eval/sandbox_backend.py`) — Modal Sandbox (legacy and V2) remains
permanently `NOT_QUALIFIED` for untrusted code execution (Phase
21B.4.7A/A.1/A.2's live CPU-quota-enforcement finding, unchanged and
unreinterpreted), and Modal GPU remains trusted-inference-only
(generated text is data there, never executed). Coding evaluation tiers,
from current Tier-1 coverage to the Tier-2 holdout target:

1. **Unit functions** (current category 4) — sufficient for control/
   strong discrimination.
2. **Debugging** (current category 5) — sufficient, extend defect
   complexity for the holdout tier.
3. **Multi-file patches** — a diff/patch must apply cleanly and pass an
   extended test suite spanning more than one file; category 7's
   structural check is the Tier-1 seed for this, needing a harder
   holdout variant.
4. **Repository reasoning** — given a small but real multi-file
   repository (not a synthetic snippet), answer questions or make a
   change that requires understanding cross-file relationships.
5. **Architecture/code-change planning** — category 6's LLM-judge
   evaluation, extended to require an actual proposed diff/plan, not
   only prose description.

The private holdout tier is where genuinely difficult repository-scale
coding/debugging tasks belong (owner spec §22) — none are authored this
phase.

## 7. Teacher/student option support

This methodology is built so the execution phase's evidence can support
any of three outcomes, decided AFTER evidence exists, never assumed
here:

- **Direct foundation model** — a deployable candidate is itself close
  enough to frontier-reference capability to serve as Genesis's base
  with no distillation step.
- **Frontier teacher → Genesis student** — a deployable candidate (e.g.
  a 27B/119B-class model) is not itself frontier-equivalent, but the
  frontier-gap metric (`GENESIS_FRONTIER_DECISION_GATES.md` §B) shows
  the gap is plausibly closeable via post-training against a frontier
  teacher's outputs, and the teacher's license permits that use
  (`GENESIS_TEACHER_STUDENT_STRATEGY.md`).
  A deployable candidate is never selected as a student merely because
  it is cheap — the frontier-gap evidence and the adaptability rubric
  (`GENESIS_FRONTIER_DECISION_GATES.md` §A.2) must both support it.
- **Hybrid** — different capability areas sourced from different
  strategies (e.g. direct-foundation for general reasoning, distillation
  for a specific weak category).

No ranking, finalist selection, or strategy choice is made in this
phase (owner spec §31).

## 8. What this document deliberately does not do

- Does not assign numeric weights to any category (see
  `GENESIS_FRONTIER_SCORING_CONTRACT.md` §4's "lock weights before
  results exist" rule).
- Does not author any Tier-2 holdout task content.
- Does not select judge models (see `GENESIS_FRONTIER_SCORING_CONTRACT.md`
  §3, extending the Phase 21B.4.8.1 judge-protocol spec with the
  execution-phase requirements only).
- Does not run, download, or spend anything (`GENESIS_FRONTIER_COST_PLAN.md`).

See the companion documents for the scoring contract, decision gates,
execution funnel, evidence schema, and cost plan this methodology
depends on.
