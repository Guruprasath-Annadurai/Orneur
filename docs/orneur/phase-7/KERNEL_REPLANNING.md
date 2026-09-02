# Kernel Replanning (Phase 7.1 spec §15-19)

Phase 7 had a real, tested `revise_plan_for_court_verdict()` mechanism with
no production caller. Phase 7.1 wires it into
`CognitiveKernel._answer_with_truth_fabric()`'s Court-invocation loop.

## The loop

```python
replan_state = ReplanState()
while True:
    case, court_verdict, court_stop_reason = await court.run(...)
    if court_stop_reason == "DELIBERATION_BUDGET_EXHAUSTED": abstain
    if court_verdict.verdict == REJECT: abstain (CRITICAL_CONTRADICTION or FALSIFICATION_FAILED)
    if court_verdict.verdict == INSUFFICIENT_EVIDENCE: abstain (COURT_INSUFFICIENT_EVIDENCE)
    if court_verdict.verdict == REVISE and replan_state.can_replan():
        reserve "replanning" budget (abstain honestly if exhausted)
        reasoning_plan = revise_plan_for_court_verdict(reasoning_plan, REVISE, replan_state)
        continue   # bounded re-run of Court
    break   # ACCEPT, or REVISE with replan budget exhausted -- proceed to generation
```

## Bounded, never infinite (spec §16, §18)

`MAX_REPLANS = 2` (unchanged from Phase 7). `ReplanState.can_replan()` is
checked before every replan attempt; once exhausted, a persistent REVISE
verdict degrades to "proceed to generation" rather than looping forever --
proven directly:
`tests/test_kernel_replanning.py::test_persistent_revise_degrades_after_max_replans_instead_of_looping_forever`
asserts Court is called exactly `MAX_REPLANS + 1` times, never more.

## Simple requests never replan (spec §15's "do NOT replan simple/direct requests")

The replan loop only runs at all inside the `if reasoning_plan.requires_court:`
branch -- a DIRECT-mode request never reaches this code, exactly as in
Phase 7's fast path (see `FAST PATH` measurements in `PHASE_7_FINAL_CLOSURE.md`).

## Court REVISE / ACCEPT / REJECT semantics (spec §18-19)

- **REVISE**: may trigger ONE bounded revision + re-run (this phase's new
  behavior) -- never "run Court again forever."
- **ACCEPT**: proceeds to generation. Does NOT authorize any tool/action
  (spec §48, unchanged from Phase 6/7) -- `verify_answer()` still
  independently re-checks the generated answer.
- **REJECT**: terminates via abstention (`CRITICAL_CONTRADICTION` or
  `FALSIFICATION_FAILED`) -- no "specifically allowed alternative-path
  revision" was added this phase; REJECT is a hard stop, matching the
  Phase 6 Arbiter's own decision order (a REJECT already means "all claims
  disputed AND real counter-evidence/unsupported-assumptions found" --
  there is no honest alternative path to revise toward without new
  evidence, which would need a fresh Truth Fabric round, not just a
  Court re-run).

## Plan versioning (spec §17)

Every replan preserves `plan_id` is NOT reused -- a NEW `ReasoningPlan`
object is created (`version = parent.version + 1`, `parent_version =
parent.version`, `revision_reason` set, `created_at` timestamped). The
Kernel's `trace_builder.record_operation_outcome(f"replan:v{parent}->v{new}:COURT_REVISE")`
records the transition as a short structured label -- no raw
chain-of-thought.

## Deterministic test coverage

`tests/test_kernel_replanning.py` drives the FULL `CognitiveKernel.execute()`
path with `CognitiveCourt.run`/`TruthFabric.assess_evidence`/
`TruthFabric.verify_answer`/`CognitiveKernel._answer_directly` monkeypatched
-- the Kernel's OWN replan-loop code runs for real, with no live Ollama
dependency. Both tests pass.
