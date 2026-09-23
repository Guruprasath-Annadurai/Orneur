# Genesis Control-Parity Specification — Phase 21B.4.16

**Prospective only. No execution occurs in this phase or from this
document. No control has been run against any task.**

## Purpose

The three registered controls (Qwen3-8B, Mistral-Nemo-Instruct-2407,
Phi-4) exist to establish a mandatory lower capability baseline under
the locked Genesis frontier methodology's control-superiority gate
(`delta_control_superiority = 0.10`,
`GENESIS_FRONTIER_DECISION_GATES.md`). For that comparison to mean
anything, every future control execution — and every future Genesis
candidate execution measured against it — must be run under a genuinely
fair, identical protocol. This specification states that requirement
explicitly, so a future evaluation phase cannot accidentally (or
otherwise) tilt the comparison in either direction.

## What must remain identical across controls (and between controls and candidates)

1. **Same semantic tasks.** Every control receives the exact same task
   set, in the exact same order, as every other control and as any
   Genesis deployable candidate being compared against it. No control
   receives an easier subset, a different task version, or additional
   context not given to the others.
2. **Same scoring.** The same judge configuration, the same rubric, the
   same deterministic/human-adjudicated scoring path used for one
   control must be used for all three, and for any candidate compared
   against them. No control-specific scoring leniency.
3. **Same evidence requirements.** Controls are held to the identical
   evidence-completeness bar as deployable candidates — the same
   generation-artifact integrity checks
   (`GenerationArtifactIntegrityError`, `MissingGenerationProvenanceError`,
   etc.), the same denominator-integrity requirements, the same
   hard-gate checks. A control result missing required evidence is
   exactly as invalid as a candidate result missing it.
4. **No extra tools.** If a task involves tool use, every control and
   candidate gets access to the identical tool set, defined identically.
   No control receives a tool a candidate doesn't, and vice versa.
5. **No extra retries.** Every control and candidate gets the same
   number of attempts under the same repeat/stability policy
   (`GENESIS_FRONTIER_SCORING_CONTRACT.md` §8.4's stability calibration).
   No silent re-rolling of a control's poor answer.
6. **No hidden hints.** No control or candidate prompt may contain
   information, formatting hints, or scaffolding not present for the
   others attempting the same task.
7. **No larger answer budgets solely because a model is a control.**
   Token/output budgets are set per task, not per model identity, and
   apply identically to controls and candidates.
8. **No intentional handicapping.** The inverse of the above also
   applies: controls must not be deliberately weakened, given worse
   prompts, or held to a stricter evidence bar than candidates, in
   order to make a Genesis candidate look artificially stronger by
   comparison. Fairness runs in both directions.

## What is allowed to differ (and why)

- **Model-specific chat-template / runtime formatting.** Each control
  and candidate has its own tokenizer chat template, its own
  reasoning/tool-call parser requirements (e.g. Qwen3-8B's
  `--reasoning-parser qwen3 --tool-call-parser hermes` vs. a candidate's
  own documented parser flags), and its own serving-engine launch
  arguments. This is necessary correctness plumbing, not an unfair
  advantage — the underlying SEMANTIC task presented to the model must
  remain identical even though the wire-level request formatting
  differs to match each model's own expected input shape.
- **Precision/quantization choices**, where explicitly authorized by
  the locked evaluation methodology's precision-escalation policy
  (`GENESIS_FRONTIER_DECISION_GATES.md` §G-equivalent for controls) —
  never chosen ad hoc to favor one model's apparent performance.

## Enforcement

This specification does not itself enforce anything — it is a written
commitment that a future evaluation-execution phase must implement and
that any evidence audit can check the actual execution logs/harness
configuration against. No code exists yet to enforce control parity
programmatically; that would be part of the (not-yet-authorized) future
evaluation execution phase's own harness design, built against this
specification's explicit requirements.

## Scope note

This document governs comparisons involving the three registered
controls. It does not authorize, imply, or perform any control
execution, any Genesis candidate execution, any benchmark, or any
capability judgment. Phase 21B.4.16 performs zero capability evaluation.
