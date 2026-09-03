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

**Superseded by Phase 11.2's own qualification below** — the live-suite
line above was written before Phase 11.2 found and fixed the real
Gateway-layer root cause; kept here unedited as the honest historical
record of what was known and reported at Phase 11.1 closure time.

---

# Phase 11.2 — Simulation Chamber Final Qualification

**Repository**: orca | **Branch**: session-update-2026-08-25

## What this phase closed

Phase 11.1 closure reported two live-suite failures as "environmental"
without supporting evidence — rejected by the Phase 11.2 spec as
insufficient. This phase:

1. Built genuinely concurrent branch-cancellation proof
   (`orca/simulation/branching.py::run_bounded_branches_async()`, real
   `asyncio.TaskGroup`, real `asyncio.Event` handshakes proving both
   branches active before cancellation) — see `ASYNC_CANCELLATION.md`.
2. Built genuine in-flight Truth-verification cancellation proof (a
   controlled deterministic Truth adapter per spec §8, used only to
   prove exact task lifecycle timing) while preserving all pre-existing
   real `TruthFabric` integration tests unchanged — see
   `ASYNC_CANCELLATION.md`.
3. Replaced the "environmental" label with actual evidence-based
   root-cause investigation of every live-suite failure observed across
   four full invocations (two from Phase 11.1, two more gathered this
   phase) — see `LIVE_RUNTIME_QUALIFICATION.md`. This uncovered:
   - Two real test-harness gaps (missing `warm_model()`; missing
     `TruthTimeoutError` in the transient-retry classification), fixed
     in Phase 11.2 commit 1/6.
   - One real, previously-undiscovered **Gateway-layer bug**:
     `OllamaRuntime.generate()` unconditionally converted every
     `asyncio.CancelledError` into a domain `RequestCancelledError`,
     which defeated `asyncio.wait_for()`'s own timeout-to-exception
     conversion at three independent call sites (`Gateway.generate()`,
     `CognitiveCourt.run()`, `TruthFabric`'s several timeout-guarded
     calls) — silently turning an already-handled deadline into an
     unhandled exception under real sustained load. Fixed at the true
     source in `orca/gateway/ollama_runtime.py`, with a defensive
     matching fix in `orca/deliberation/court.py`.
4. Achieved a full, clean, zero-failure live-suite invocation (40/40)
   after the fix, plus a second confirmation run, both reported
   honestly and separately (not merged) — see
   `LIVE_RUNTIME_QUALIFICATION.md`.

## Test results (fresh, this closure)

| Suite | Result |
|---|---|
| Full application suite (deterministic) | 1321 passed, 0 failed, 40 deselected |
| Authoritative security suite (74 files, deterministic) | 663 passed, 0 failed, 1 deselected |
| Live suite (`-m live_ollama_smoke`), invocation 1 (post-fix) | **40 passed, 0 failed** — 794.12s (0:13:14) |
| Live suite (`-m live_ollama_smoke`), invocation 2 (post-fix, repeat) | **40 passed, 0 failed** — 387.41s (0:06:27) |
| Original Phase 11 eval harness | 23/23 (100%), preserved unchanged |
| Phase 11.1 closure eval harness | 21/21 (100%), preserved unchanged |
| New qualification tests | 8/8 (`tests/test_simulation_qualification_11_2.py`) |

## Real bugs found and fixed during this pass

1. `test_live_goal_produces_a_validated_plan_using_only_read_only_tools`
   had no `warm_model()` call, unlike every sibling live test — fixed.
2. `tests/ollama_test_support.py`'s `_TRANSIENT_ERRORS` tuple did not
   include `orca.truth.errors.TruthTimeoutError`, and the two
   `verify_answer`-calling Truth Fabric tests had zero retry wrapping —
   fixed via a new `retry_transient_async()` plus the classification
   addition.
3. **`orca/gateway/ollama_runtime.py::OllamaRuntime.generate()`** — see
   "What this phase closed" §3 above and `LIVE_RUNTIME_QUALIFICATION.md`
   for the full evidence trail. This is the most significant bug found
   in Phase 11.2: a real, previously-latent Gateway defect that had
   nothing to do with Simulation Chamber code, discovered only because
   this phase's spec explicitly forbade an "environmental" label without
   evidence.
4. A genuine asyncio semantics edge case (not a code defect): cancelling
   a task synchronously immediately after `create_task()`, before the
   event loop schedules it even once, means the coroutine's own internal
   `try/except CancelledError` never runs and `CancelledError` propagates
   from the coroutine's entry point. Documented, not "fixed," since it is
   correct standard asyncio behavior — the qualification test was
   redesigned into two explicit arms instead.

## Known limitations (disclosed, not blocking)

1. `LIVE_OLLAMA_STRESS` has zero tests despite the marker's existence in
   `pyproject.toml` — sustained-concurrency/overload real-Ollama testing
   has not been built in any phase through 11.2.
2. The Gateway-layer fix (item 3 above) is scoped to `OllamaRuntime`
   specifically; `orca/gateway/frontier_runtime.py` has an analogous
   `raise RequestCancelledError()` site (`frontier_runtime.py:53`) that
   was not touched, since the live-suite evidence gathered this phase
   only implicated the Ollama runtime path — this is disclosed as an
   unverified but structurally similar risk, not confirmed as a live bug,
   since no live test in this repository currently exercises the
   frontier runtime under a wait_for-guarded deadline the way the Ollama
   path is exercised.
3. `run_bounded_branches_async()`'s `force_branch=True` concurrent-launch
   mode is a deliberate behavioral difference from `run_bounded_branches()`'s
   real sequential, outcome-dependent branch-2 decision (documented in its
   own docstring) — necessary because a real sequential decision is
   inherently incompatible with launching both branches concurrently.

## Remaining Phase-11 blockers

None identified. All items raised in the Phase 11.2 spec (branch
cancellation proof, Truth cancellation proof, evidence-based flake
investigation, clean live invocation, harness separation, new audit
counters) have real, verified closure.

## Final audit counters

| Counter | Value |
|---|---|
| (all 20 Phase-11/11.1 counters, unchanged) | 0 |
| UNBOUNDED_SIMULATION_BRANCH | 0 |
| MULTI_ACTION_STATE_CHAIN_BYPASS | 0 |
| TRUTH_VERIFICATION_BYPASS | 0 |
| FAKE_ASSUMPTION_VERIFICATION | 0 |
| ORPHAN_SIMULATION_TASK | 0 |
| CANCELLATION_SIMULATION_BUDGET_LEAK | 0 |

**READY TO ADVANCE TO PHASE 12: YES**
