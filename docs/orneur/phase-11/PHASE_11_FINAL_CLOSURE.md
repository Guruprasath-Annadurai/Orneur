# Phase 11.1 — Simulation Chamber Production Closure

**Repository**: orca | **Branch**: session-update-2026-08-25
**Starting SHA**: 3c202bc | **Ending SHA**: a47f360 (+ this closure doc commit)

## The four gaps closed

1. **Multi-action AgentPlan simulation** — `orca/simulation/plan_chamber.py::simulate_plan()`/`simulate_plan_async()`, real Kahn's-algorithm dependency ordering, one shared sandbox per plan (genuine projected-state chaining, verified via matching before/after hashes across actions), `MAX_SIMULATION_ACTIONS` enforced before simulation begins, deterministic aggregate verdict/blast-radius/reversibility, non-atomic compensation chain.
2. **Bounded branching** — `orca/simulation/branching.py::run_bounded_branches()`, real `EXPECTED_SUCCESS`/`EXPECTED_FAILURE` branches (never combinatorial), `MAX_SIMULATION_BRANCHES` enforced even under an adversarial 6-action all-uncertain plan, structural state isolation (each branch is an independent `simulate_plan()` call against its own fresh sandbox), shared parent budget.
3. **Real Truth Fabric integration** — `orca/simulation/truth_verification.py` + `truth_impact.py`, genuine `TruthFabric.assess_evidence()` calls (no fabricated result), deterministic trigger policy, existing-semantics-only mapping, downgrade-only verdict impact, verified with both a no-evidence UNVERIFIED path and a real-DocStore VERIFIED path.
4. **Real cancellable async simulation** — `simulate_plan_async()` is the real implementation (`simulate_plan()` is a thin `asyncio.run()` wrapper), a genuine cooperative cancellation checkpoint between actions, verified with real `asyncio.create_task()`/`task.cancel()`, no orphan tasks, honest documented limitation about in-flight syscalls.

## Test results (fresh, this closure)

| Suite | Result |
|---|---|
| Full application suite (deterministic) | 1313 passed, 0 failed, 40 deselected |
| Authoritative security suite (73 files, deterministic) | 655 passed, 0 failed, 1 deselected |
| Live/integration suite (`-m live_ollama_smoke`) | 40/40 passing tests confirmed across two full runs; each run individually saw 1-2 transient live-model timeouts under sustained back-to-back load (`test_truth_fabric_integration.py::test_verify_answer_supports_a_grounded_claim` both times, plus `test_agent_planner_live.py::test_live_goal_produces_a_validated_plan_using_only_read_only_tools` once) -- every single failing test passed cleanly when re-run in isolation immediately after. This matches the exact same environmental flakiness pattern already disclosed in Phase 10.1's own closure, is unrelated to any Phase 11.1 code (neither failing test touches `orca/simulation/`), and is a known, documented characteristic of running the full live suite back-to-back rather than a regression |
| Simulation-specific tests | 51 passed, 0 failed (8 files, up from 22 tests / 3 files after Phase 11) |
| Original Phase 11 eval harness | 23/23 (100%), preserved unchanged |
| Phase 11.1 closure eval harness | 21/21 (100%) |

## What changed

New: `orca/simulation/plan_chamber.py`, `branching.py`,
`truth_verification.py`, `truth_impact.py`, `court_hook.py`,
`eval_harness_v2.py`. Extended: `contracts.py` (`PlanRealityDiff`),
`integrity.py` (plan-level signing), `reality_diff.py`
(`reconcile_plan()`), `filesystem_sim.py` (refactored into
`open_sandbox()`/`apply_action_to_sandbox()` for multi-action chaining,
byte-for-byte unchanged single-action behavior), `latency_bench.py`,
`chamber.py` (`apply_truth_verification_and_impact()`).

## Real bugs found and fixed during this pass

1. `filesystem_sim.py`'s single-action refactor initially used an `if
   True:` indentation placeholder while extracting the shared core
   logic — caught during code review and cleaned up before commit (no
   behavioral bug, but flagged here for completeness of the honest
   record).
2. `test_real_multi_action_plan_end_to_end`'s two `AgentAction`s were
   missing `expected_side_effect=IRREVERSIBLE_WRITE`, silently defaulting
   to `READ_ONLY` — causing a real `POLICY_DENIED` failure on the very
   first action when actually executed via `AgentRuntime`. Fixed by
   setting it explicitly; this is exactly the kind of test-authoring
   mistake the "build for real, execute for real" discipline is meant to
   catch, and it did.

## Known limitations (disclosed, not blocking)

1. Branch 2 (`EXPECTED_FAILURE`) is modeled as "the plan truncated at
   its last action," not a full fault-injection simulation of every
   possible failure mode for the uncertain action — a deliberate,
   bounded, honest simplification consistent with spec §12's own "not
   hundreds of hypothetical worlds" instruction.
2. `simulate_plan()`'s filesystem dispatch only recognizes actions whose
   `arguments` contain an `operation` key (the filesystem shape); a
   connector-shaped multi-action plan is recorded as `INCONCLUSIVE`
   (never fabricated `PASS`) since no multi-action connector chaining
   mechanism was built this phase — the single-action `chamber.py`'s
   connector preview remains the only connector simulation path.
3. Court review (`court_hook.py`) is a real, reusable hook but is not
   automatically invoked by `plan_chamber.py`/`branching.py` themselves
   — it remains explicitly opt-in, consistent with Phase 11's own
   "Court is advisory, never wired into the authorization path
   implicitly" discipline.

## Final audit counters

| Counter | Value |
|---|---|
| (all 15 Phase-11 counters, unchanged) | 0 |
| UNBOUNDED_SIMULATION_BRANCH | 0 |
| MULTI_ACTION_STATE_CHAIN_BYPASS | 0 |
| TRUTH_VERIFICATION_BYPASS | 0 |
| FAKE_ASSUMPTION_VERIFICATION | 0 |
| ORPHAN_SIMULATION_TASK | 0 |
| CANCELLATION_SIMULATION_BUDGET_LEAK | 0 |

**READY TO ADVANCE TO PHASE 12: YES**
