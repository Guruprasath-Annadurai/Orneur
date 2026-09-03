# Phase 10 — Kill Switch

`orca.godmode.kill_switch` — a plain file flag under
`ORCA_HOME/godmode/kill_switch.flag`. `activate()`/`deactivate()`/
`is_active()`/`status()`.

## Behavior

- `resolve_lease()` checks `kill_switch_active()` FIRST, before even
  looking up the lease — while active, EVERY elevated action resolves to
  DENY with `kill_switch_active=True` in the decision trace, regardless
  of how valid the lease itself is.
- Restart-safe: the flag is a file, not in-process state, so a process
  restart does not silently clear an active kill switch (spec §58's
  restart-safety requirement applied to the kill switch itself).
- Normal-mode (non-elevated) operations are unaffected — the kill switch
  is only ever consulted inside `resolve_lease()`, which is only reached
  when an action is already being considered for elevation.

## No model-reachable path (spec §15's "must not depend on model
behavior")

`orca.godmode.kill_switch` is never imported by anything under
`orca/agent/` (tool code, planner, or runtime) — verified in
`tests/test_godmode_security.py::test_no_model_reachable_function_can_disable_kill_switch`
via AST inspection of every file in `orca/agent/`. There is no tool spec
anywhere that exposes `activate`/`deactivate` to an `AgentToolRegistry`.
Only trusted platform/operator code (a human or an ops script) can call
these functions directly in Python.

## Verified under an active elevated session

`tests/test_godmode_security.py::test_kill_switch_denies_new_elevated_actions`
activates the kill switch while a valid, unexpired, unrevoked lease
exists, confirms the very next resolution attempt is denied, then
deactivates it in a `finally` block (test hygiene — the real switch used
in that test is isolated per-test via `tests/conftest.py`'s autouse
fixture, never the developer's real kill switch file).
