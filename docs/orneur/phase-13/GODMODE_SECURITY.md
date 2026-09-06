# Phase 13 — Godmode Security

## Lease forgery (spec §34) — already fully covered

`tests/test_godmode_security.py` already includes, verbatim matching the
spec's own attack list: `test_lease_tamper_any_signed_field_fails_integrity`
(parametrized across signed fields), `test_fabricated_lease_id_resolves_to_deny`,
`test_unsigned_lease_fails_integrity`, `test_model_injection_text_cannot_construct_a_valid_lease`,
`test_scope_matching_rejects_prefix_confusion`,
`test_client_supplied_time_cannot_extend_a_lease`,
`test_future_issued_at_does_not_bypass_expiry_check`,
`test_lease_use_count_cannot_go_negative`.
`tests/test_godmode_exact_argument_binding.py` covers argument-hash
tampering, binding-mode tampering, replay-matrix scenarios.

## Concurrency (spec §35) — already covered

`test_concurrent_actions_racing_a_one_use_lease_only_one_succeeds`,
`test_expiry_checked_before_every_action_not_only_at_session_creation`
(`tests/test_godmode_concurrency_and_e2e.py`).

## Kill switch (spec §36) — already covered

`test_kill_switch_denies_new_elevated_actions`,
`test_no_model_reachable_function_can_disable_kill_switch`
(`tests/test_godmode_security.py`).

## File-scope attacks (spec §37) — already covered

`test_file_godmode_end_to_end` (`tests/test_godmode_concurrency_and_e2e.py`);
directory-scope/symlink-escape enforcement lives in
`orca/godmode/file_elevation.py`'s `_resolve_within_root`/`_is_denied`,
also reused this phase by `orca/learning/registry_isolation.py` (Phase
12.1) for an unrelated but structurally identical purpose.

## New this phase

Behavioral (not structural-only) confirmation via
`tests/test_redteam_cross_layer_chains.py::
test_connector_content_through_court_accept_still_cannot_reach_godmode_issuance`
that even a worst-case Court ACCEPT verdict built from connector-injected
content cannot reach `issue_lease()` — complementing the existing
structural `test_court_accept_cannot_activate_godmode`.

## Result

`GODMODE_FORGERY_BYPASS = 0`, `GODMODE_USECOUNT_RACE = 0`,
`KILL_SWITCH_RACE_BYPASS = 0` — all confirmed by pre-existing, passing
tests plus this phase's one new behavioral test.
