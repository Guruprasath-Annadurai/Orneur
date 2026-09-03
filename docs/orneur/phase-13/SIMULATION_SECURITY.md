# Phase 13 — Simulation Security

All of spec §38-42 already has real, passing coverage from Phase
11/11.1/11.2, confirmed by direct file inspection this phase (not
re-derived):

| Spec item | Existing test (`tests/test_simulation_security.py` unless noted) |
|---|---|
| §38 result forgery / field mutation | `test_model_or_tool_content_cannot_forge_a_valid_simulation_result`, `test_only_chamber_produced_results_carry_a_valid_signature`, `test_verdict_injection_via_field_mutation_is_detected` |
| §39 sandbox escape (symlink/traversal) | `test_sandbox_cannot_write_outside_root_via_traversal`, `test_sandbox_cannot_escape_via_symlink` |
| §40 simulation/reality confusion | `test_simulation_never_calls_a_real_connector_write_function` |
| §41 staleness | `test_stale_preview_detected_after_resource_version_change` |
| §42 Godmode race | `test_lease_revoked_between_simulation_and_execution_denies`, `test_kill_switch_activated_after_simulation_pass_denies_execution` |
| Cross-tenant | `test_cross_tenant_simulation_blocked_for_connectors`, `test_cross_tenant_lease_cannot_be_used_for_simulation_compatibility_check` |
| Secret exposure | `test_simulation_trace_does_not_expose_raw_secret_arguments`, `test_simulation_result_dataclass_has_no_raw_credential_field` |

No new tests added this phase — the existing coverage already directly
matches the spec's own attack list, verbatim in several cases.

## Result

`SIMULATION_RESULT_FORGERY_BYPASS = 0`, `SIMULATION_SANDBOX_ESCAPE = 0`,
`SIMULATION_STALE_BYPASS = 0`.
