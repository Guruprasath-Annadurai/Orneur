# Phase 11 — Simulation Modes

| Mode | Status | Real mechanism |
|---|---|---|
| `STATIC_ANALYSIS` | SUPPORTED (all tools, cheapest mode) | Requirement-policy + capability-declaration inspection; no execution. |
| `DRY_RUN` | UNAVAILABLE (no tool/provider in this codebase exposes a native dry-run endpoint) | Disclosed honestly — not fabricated. |
| `SANDBOX_EXECUTION` | SUPPORTED for filesystem writes | Real temp copy-on-write tree (`filesystem_sim.py`); no production path escape. |
| `STATE_PROJECTION` | SUPPORTED | `worldstate_projection.py` — a deep-copied, distinctly-IDed `WorldState`. |
| `COUNTERFACTUAL` | SUPPORTED (reused, not rebuilt) | Phase 6's `orca.deliberation.counterfactual` — model-based "what if," never conflated with execution. |
| `SHADOW_EXECUTION` | UNAVAILABLE | No shadow-routing/canary-deployment infrastructure exists anywhere in this codebase (confirmed in the Phase 11 audit). |
| `PROVIDER_PREVIEW` | SUPPORTED for `TICKETING` only | Phase 9's real `FakeProviderState`/`fake_write()`, isolated per simulation. `DOCUMENT_STORE` and every other connector family are UNAVAILABLE (disclosed, not fabricated — see CONNECTOR_SIMULATION.md). |

`ToolSimulationCapability.support_for(mode)` returns
`SimulationSupportLevel.SUPPORTED`/`UNAVAILABLE` per this table, declared
explicitly per tool in `orca/simulation/tool_capability_registry.py` —
never inferred from a tool's name.

## No fabricated modes

Per spec §5's explicit instruction ("do not claim support for a mode
unless a real mechanism exists"), `DRY_RUN` and `SHADOW_EXECUTION` are
both UNAVAILABLE everywhere in this codebase today — there is no
provider-neutral "native dry-run" call anywhere, and no shadow/canary
deployment mechanism exists at all (confirmed by
`CURRENT_SIMULATION_ARCHITECTURE.md`'s audit). A future phase adding a
real provider with a genuine preview API should register it via
`tool_capability_registry.register_capability()` rather than this
module claiming support speculatively.
