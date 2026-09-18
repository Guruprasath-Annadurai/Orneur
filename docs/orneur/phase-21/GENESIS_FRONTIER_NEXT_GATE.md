# Genesis Frontier — Next Gate

## Where this phase leaves things

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

**Not started this phase.** The next evidence-gathering step, if
authorized, would be a resource-scoped, evidence-based comparison
among the smallest/most tractable credible candidates this research
surfaced — most plausibly **Qwen3.8-27B (dense, Apache 2.0)** as the
first real deployable-candidate touch, given it is the only frontier-
lineage model in this research pass that fits realistic Modal GPU
compute within the owner's included-credit budget without immediately
exhausting it. This would NOT be a frontier-giant evaluation (those
remain compute-prohibitive per the Compute Matrix doc) — it would be a
first real look at whether a small, permissively-licensed sibling of a
credibly frontier-tier flagship shows measurably strong capability on
ORNEUR's own evaluation methodology, still to be designed.

Proposed phase name (not authorized, not started):
`PHASE 21B.4.9 — GENESIS DEPLOYABLE-CANDIDATE BENCHMARK METHODOLOGY DESIGN`
— to design a fair, evidence-based comparison methodology appropriate
to whichever candidates the owner ultimately authorizes for real
evaluation, BEFORE exposing `genesis-eval-v1` to any of them.

## What remains explicitly locked

- Phase 21C (training, in any form)
- Canonical Genesis base change
- Any model promotion or "winner" declaration
- `genesis-eval-v1` execution, inspection, or freezing
