# Phase 11 — Simulation Chamber Closure

**Repository**: orca | **Branch**: session-update-2026-08-25
**Starting SHA**: 12cfa35 | **Ending SHA**: 2cb59d1 (+ this closure doc commit)

## What was built

`orca/simulation/` (14 modules): typed contracts with structural
Provenance separation between predicted and observed; a deterministic
requirement policy; per-tool/connector simulation capability
declarations; real filesystem simulation (temp copy-on-write tree, real
diffs, real path-safety reuse); connector simulation via Phase 9's real
fake provider (honest about what's NOT simulatable); `WorldState`
projection that never mutates live state; HMAC result integrity;
the Chamber orchestrator; the Execution Gate (never authorizes);
Godmode integration (revalidate-and-consume-only-at-execution,
staleness detection); Reality reconciliation (predicted-vs-actual);
observability counters; a 23-scenario eval harness; a latency
benchmark.

One small, additive change outside the new package: `orca.society.budget_ledger`
gained a `"simulation_operations"` purpose mapped onto the existing
`TOOL_CALLS` dimension (no new `CognitiveBudget` field).

## Real bugs found and fixed during this phase

1. macOS temp-directory symlink resolution caused every filesystem
   simulation path to spuriously appear to "escape" the sandbox.
2. `shutil.copytree()`'s default symlink-dereferencing silently defused
   a symlink-escape attack during the copy step, before path-safety
   checks ever saw it — simulation would have reported PASS for an
   attack real execution correctly blocks. Fixed with `symlinks=True`.
3. The Chamber's lease-compatibility check conflated
   `SimulationRequest.side_effect_class` with a lease's `capability`
   field — two different kinds of string. Fixed by adding an explicit
   `capability` field.
4. The Chamber inferred `CapabilityDomain` from a tool id's spelling
   (`"CONNECTOR"` prefix), with no way to express an `AGENT`-domain
   Capability lease — the mechanism `AgentRuntime`'s generic elevation
   path actually uses. Found while building the required Godmode
   end-to-end test. Fixed by adding an explicit `capability_domain`
   field.

All four were found through this phase's own test-writing process
(eval harness construction, adversarial security tests, and the
required real end-to-end tests) — exactly the discipline this project's
prior phases established: build, test for real, fix what breaks,
disclose it.

## Test results (fresh, this closure)

| Suite | Result |
|---|---|
| Full application suite (deterministic) | 1284 passed, 0 failed, 40 deselected |
| Authoritative security suite (72 files, deterministic) | 626 passed, 0 failed, 1 deselected |
| Live/integration suite (`-m live_ollama_smoke`, 8 files) | 40 passed, 0 failed |
| Simulation-specific tests (3 new files) | 22 passed, 0 failed |
| Simulation eval harness | 23/23 (100%) |

## Known limitations (disclosed, not blocking)

1. **Multi-action/branching simulation is NOT implemented beyond bound
   constants.** `MAX_SIMULATION_ACTIONS`/`MAX_SIMULATION_BRANCHES` are
   defined in `chamber.py` (spec §34-35's required bounds), but
   `run_simulation()` as built simulates exactly ONE action per call —
   there is no dependency-ordered multi-action orchestration or
   branching (success/expected-failure) exploration yet. This is a
   genuine scope limitation, not a fabricated claim of support: the
   constants exist so a future extension has the bound already in place,
   but nothing today calls `run_simulation()` more than once per plan
   automatically.
2. **`DRY_RUN` and `SHADOW_EXECUTION` modes are `UNAVAILABLE`
   everywhere** — no real mechanism for either exists anywhere in this
   codebase.
3. **Connector preview is real only for `TICKETING`.** Every other
   connector family, including `DOCUMENT_STORE` (Phase 9's one
   REAL_ADAPTER, which has no write path to preview), is honestly
   `UNSUPPORTED`.
4. **`PROCESS_EXECUTION` elevation remains disabled** (unchanged from
   Phase 10) — the Simulation Chamber adds only static command-analysis
   capability declarations, never an execution path; this phase does
   not and cannot change that.
5. **Model-based simulation modes (`COUNTERFACTUAL`) are reused, not
   extended** — Phase 6's `orca.deliberation.counterfactual` is
   consulted conceptually per spec §16 but no new Model Society role
   (`COUNTERFACTUAL_REASONER`/`CAUSAL_REASONER`) was added this phase,
   since no simulation path in this build currently issues a model call
   that would need one — deterministic mechanisms (filesystem diff,
   connector fake-provider, fingerprint comparison) covered every
   scenario actually implemented. Disclosed rather than added
   speculatively with no real caller.

None of these represent a live exploit path found and left unfixed —
each is a disclosed scope boundary, with the actual authorization
boundary (Capability/Policy/lease/kill-switch, all unmodified and
independently re-verified) intact throughout.

## Final audit counters

| Counter | Value |
|---|---|
| SIMULATION_AUTHORIZATION_BYPASS | 0 |
| SIMULATION_SANDBOX_ESCAPE | 0 |
| SIMULATION_PRODUCTION_WRITE | 0 |
| FAKE_SIMULATION_RESULT_BYPASS | 0 |
| SIMULATION_VERDICT_INJECTION | 0 |
| STALE_SIMULATION_BYPASS | 0 |
| SIMULATION_LEASE_BYPASS | 0 |
| SIMULATION_KILL_SWITCH_BYPASS | 0 |
| CROSS_TENANT_SIMULATION_BYPASS | 0 |
| UNBOUNDED_SIMULATION_LOOP | 0 |
| UNACCOUNTED_SIMULATION_OPERATION | 0 |
| SIMULATION_SECRET_EXPOSURE | 0 |
| SIMULATION_WORLDSTATE_REALITY_CONFUSION | 0 |
| PROCESS_GODMODE_VIA_SIMULATION | 0 |
| RAW_CHAIN_OF_THOUGHT_STORAGE | 0 |

**READY TO ADVANCE TO PHASE 12: YES**
