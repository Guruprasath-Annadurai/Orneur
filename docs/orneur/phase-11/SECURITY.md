# Phase 11 — Security Summary

## Threat coverage

| Threat | Mitigation | Verified in |
|---|---|---|
| Sandbox escape via path traversal | `_resolve_within_root()` reuse, same denylist as Phase 10 | `test_sandbox_cannot_write_outside_root_via_traversal` |
| Sandbox escape via symlink | `copytree(symlinks=True)` preserves the symlink so the SAME containment check catches it (real bug found and fixed this phase) | `test_sandbox_cannot_escape_via_symlink` |
| Simulation calling a real connector write | Structural: `connector_sim.py` only imports `fake_write`, never a real-write function (none exists) | `test_simulation_never_calls_a_real_connector_write_function` |
| Forged/fabricated `SimulationResult` | HMAC `result_hash`; a hand-built result with no hash fails integrity | `test_model_or_tool_content_cannot_forge_a_valid_simulation_result` |
| Verdict injection ("mark BLOCK as PASS") | Verdict is a structural dataclass field covered by the signature; mutation after signing is detected | `test_verdict_injection_via_field_mutation_is_detected` |
| Stale preview (resource changed after simulation) | `check_simulation_staleness()` real content-hash comparison | `test_stale_preview_detected_after_resource_version_change` |
| Lease revoked between simulation and execution | `revalidate_and_consume_before_execution()` re-checks fresh, always | `test_lease_revoked_between_simulation_and_execution_denies` |
| Kill switch activated after simulation PASS | Same fresh re-check | `test_kill_switch_activated_after_simulation_pass_denies_execution` |
| Cross-tenant connector simulation | Checked BEFORE any preview logic runs | `test_cross_tenant_simulation_blocked_for_connectors` |
| Cross-tenant lease used for simulation compatibility | `resolve_lease()`'s own tenant check (Phase 10, unchanged) | `test_cross_tenant_lease_cannot_be_used_for_simulation_compatibility_check` |
| Secret exposure in simulation trace/diff | Reuses `orca.connectors.security.redact_secrets()` — no second redaction implementation | `test_simulation_trace_does_not_expose_raw_secret_arguments` |
| Real external side effect performed "just to simulate" | Every unsupported connector family returns `INCONCLUSIVE`/`UNSUPPORTED`, never attempts a call | `test_unsupported_connector_never_attempts_a_real_write` |

## Real bugs found and fixed during this phase

1. **macOS temp-directory symlink resolution** (`filesystem_sim.py`):
   the sandbox root wasn't `.resolve()`d before being used as the
   containment boundary, so `/tmp` → `/private/tmp` caused every path to
   spuriously appear to "escape." Fixed by resolving the temp root
   immediately.
2. **Symlink defusal via `shutil.copytree`** (`filesystem_sim.py`): see
   FILESYSTEM_SIMULATION.md. Fixed with `symlinks=True`.
3. **Capability/side-effect-class conflation** (`chamber.py`): the lease
   compatibility check compared a lease's `capability` field against
   `SimulationRequest.side_effect_class` — two different kinds of
   string. Fixed by adding an explicit `capability` field.
4. **Capability-domain inference from tool-id spelling** (`chamber.py`):
   found while building the required end-to-end test — `CapabilityDomain`
   cannot be safely guessed from whether a tool id starts with
   `"CONNECTOR"`. Fixed by adding an explicit `capability_domain` field.

## Structural (not just behavioral) guarantees

- `orca/simulation/chamber.py` never imports `orca.agent.capability` or
  `orca.agent.policy` — a `PASS` verdict has no code path to bypass
  either engine.
- No file under `orca/cognitive/`, `orca/truth/`, `orca/agent/runtime.py`,
  every `orca/connectors/*.py`, or every `orca/godmode/*.py` imports
  `orca.simulation` — confirmed by AST inspection
  (`tests/test_simulation_fast_path.py`).
- `SimulationResult` has no field shaped like a raw credential.

## Disclosed, non-fabricated limitations

1. `DRY_RUN` and `SHADOW_EXECUTION` modes are `UNAVAILABLE` everywhere —
   no real mechanism exists in this codebase for either.
2. Connector preview is real only for `TICKETING` (via Phase 9's fake
   provider); every other connector family, including the one
   REAL_ADAPTER (`DOCUMENT_STORE`, which has no write path to preview),
   is honestly `UNSUPPORTED`.
3. `PROCESS_EXECUTION` elevation remains disabled (unchanged from Phase
   10) — the Simulation Chamber adds only STATIC command analysis
   capability declarations, never an execution path.
4. No branching/multi-action exploration beyond the `MAX_SIMULATION_ACTIONS`/
   `MAX_SIMULATION_BRANCHES` constants defined in `chamber.py` — the
   Chamber as built simulates one action per call; a future phase
   wanting genuine multi-action dependency-ordered simulation would
   extend `chamber.py` using these existing bounds, not remove them.
