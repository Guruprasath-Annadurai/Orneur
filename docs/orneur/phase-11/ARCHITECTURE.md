# Phase 11 — Simulation Chamber Architecture

## Canonical rule

```
simulation result != real observation
simulation success != authorization
```

Every module in `orca/simulation/` is built so this cannot be violated
structurally, not just by convention:

- `PredictedEffect`/`SimulationResult` are always tagged
  `Provenance.SIMULATION`, distinct from `TOOL_OBSERVATION`/
  `CONNECTOR_OBSERVATION`/`TRUTH_EVIDENCE`/`USER_INPUT`.
- `chamber.py::run_simulation()` never imports or calls
  `orca.agent.capability.check_capabilities()` or
  `orca.agent.policy.evaluate_policy()` (verified structurally in
  `orca/simulation/eval_harness.py`'s own scenario 13) — a `PASS`
  verdict never bypasses those.
- `worldstate_projection.py::project_worldstate()` always deep-copies
  the parent `WorldState` — the original is provably unmutated after
  every call.

## Canonical flow (spec §2)

```
AgentPlan -> ActionRequest -> Capability/Policy preliminary eligibility
    -> Simulation Requirement Policy (orca/simulation/requirement_policy.py)
    -> Simulation Chamber (orca/simulation/chamber.py)
    -> SimulationResult (signed, orca/simulation/integrity.py)
    -> Truth/Court/Risk review where applicable
    -> Execution Gate (orca/simulation/execution_gate.py)
        -> ALLOW_TO_PROCEED_TO_AUTHORIZATION  (NOT authorization itself)
    -> Capability Engine (unmodified, orca.agent.capability)
    -> Policy Engine (unmodified, orca.agent.policy)
    -> Godmode lease revalidation + consumption
       (orca/simulation/godmode_integration.py, immediately before execution)
    -> budget -> actual Tool/Connector execution -> Observation
    -> RealityDiff (orca/simulation/reality_diff.py)
```

## Package layout (`orca/simulation/`)

| Module | Responsibility |
|---|---|
| `contracts.py` | All typed dataclasses/enums — no loose-dict protocol. |
| `requirement_policy.py` | Deterministic `decide_simulation_requirement()`. |
| `tool_capability_registry.py` | Per-tool/connector declared simulation support (never inferred from name). |
| `filesystem_sim.py` | Real, deterministic filesystem simulation (temp copy-on-write tree). |
| `connector_sim.py` | Connector preview via Phase 9's real `FakeProviderState`. |
| `worldstate_projection.py` | Hypothetical `WorldState`, never mutates the live one. |
| `fingerprint.py` | Real content-hash fingerprints; honest `UNAVAILABLE` elsewhere. |
| `integrity.py` | HMAC tamper-evidence for `SimulationResult`. |
| `chamber.py` | The orchestrator — `run_simulation()`. |
| `execution_gate.py` | `evaluate_execution_gate()` — never authorizes. |
| `godmode_integration.py` | Lease revalidate-and-consume-at-execution, staleness checks. |
| `reality_diff.py` | Predicted-vs-actual reconciliation. |
| `audit.py` | Structured, non-sensitive observability counters. |
| `eval_harness.py` | 23 deterministic scenarios (spec §74). |
| `latency_bench.py` | Framework-overhead-only latency measurement (spec §77). |

## Dependency direction (verified structurally)

`orca.simulation` depends on `orca.godmode`, `orca.connectors`, and
`orca.agent.contracts` — never the reverse. `orca.cognitive.kernel`,
`orca.truth.truth_fabric`, `orca.agent.runtime`, every `orca.connectors`
module, and every `orca.godmode` module never import `orca.simulation`
at all (AST-verified, `tests/test_simulation_fast_path.py`).

## What Phase 11 deliberately did NOT modify

`orca.agent.capability.check_capabilities()`,
`orca.agent.policy.evaluate_policy()`,
`orca.connectors.policy.evaluate_connector_policy()`,
`orca.godmode.resolution.resolve_lease()`/`resolve_and_consume_lease()`
are all byte-for-byte unchanged. The one small, additive exception is
`orca.society.budget_ledger.py`'s `_PURPOSE_TO_DIMENSION` dict, which
gained a `"simulation_operations"` entry mapped onto the existing
`TOOL_CALLS` dimension (no new `CognitiveBudget` field) — verified not
to regress any of the 19 pre-existing budget-ledger tests.
