# Genesis Frontier — Next Gate

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

**Not started this phase.** With the methodology now locked (see the
Phase 21B.4.9 update above), the next evidence-gathering step, if
authorized, is the FIRST stage of the execution funnel
(`GENESIS_FRONTIER_EXECUTION_PLAN.md` Stage 0 — license/identity/
runtime eligibility) against a resource-scoped subset of the candidate
pool. `GENESIS_FRONTIER_EXECUTION_PLAN.md` §"Pre-freeze evidence-
preservation gate" identifies one small, well-scoped code addition
(re-walking every raw-response file's continued existence/integrity
immediately before the first real baseline freeze) that the execution
phase's tooling must add before Stage 8 can produce a trustworthy
foundation-decision package — this is not implemented yet and is
explicitly deferred to that phase.

Proposed phase name (not authorized, not started):
`PHASE 21B.4.10 — GENESIS CANDIDATE-EXECUTION QUALIFICATION GATE`
— to perform Stage 0 (license/identity/runtime eligibility, per
`GENESIS_FRONTIER_EXECUTION_PLAN.md`) for the deployable-candidate pool
and controls, add the pre-freeze evidence-preservation check the
execution plan identifies as a mandatory prerequisite, and confirm the
$0-cost screening plan (`GENESIS_FRONTIER_COST_PLAN.md`) against live
Modal billing before any real generation is attempted — still NOT
authorizing actual candidate execution, `genesis-eval-v1` exposure, or
any frontier-model evaluation.

## What remains explicitly locked

- Phase 21C (training, in any form)
- Canonical Genesis base change
- Any model promotion or "winner" declaration
- `genesis-eval-v1` execution, inspection, or freezing
- Any real candidate download or evaluation
- Private frontier-holdout task authoring
- Any aggregate scoring formula or judge-model selection
