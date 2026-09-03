# Phase 10 — Agent Runtime Integration

## Additive, backward-compatible wiring

`AgentRuntime.__init__` gained two new keyword-only parameters, both
defaulting to `None`:

- `tenant_id: str | None = None`
- `lease_resolver=None` — a callable `(AgentAction) -> str | None`
  naming ONE candidate lease id for that action, or `None`.

Every pre-Phase-10 caller/test is unaffected — confirmed by the full
1237-test application suite passing unchanged, and by
`tests/test_godmode_fast_path.py::test_agent_runtime_without_lease_resolver_never_touches_godmode_module`
proving `orca.godmode` is never even imported for a run that doesn't
supply both.

## `_authorize()` flow (spec §31-32)

1. Normal `check_capabilities()` + `evaluate_policy()` run exactly as
   they did before Phase 10 (unmodified).
2. Only if the result is `DENY` or `REQUIRE_APPROVAL`, AND both
   `tenant_id` and `lease_resolver` were supplied, `_try_elevate()` runs:
   - Calls `lease_resolver(action)` for exactly one candidate lease id.
   - Computes the effective capability set via
     `orca.godmode.capability.compute_effective_capabilities()` (feeding
     the SAME unmodified `check_capabilities()`).
   - Re-evaluates via `orca.godmode.policy.evaluate_elevated_policy()`
     (which itself re-runs the unmodified `evaluate_policy()` first).
3. `ActionAuthorization.elevated_action_class` is set to
   `"ELEVATED_ACTION"` only if step 2 resolves ALLOW; otherwise it stays
   `"NORMAL_ACTION"` and the ORIGINAL normal-policy decision is what gets
   recorded (never silently replaced by a failed elevation attempt).
4. `AgentTrace.elevated_action_ids` records every action_id that
   executed as `ELEVATED_ACTION` — explicit in the runtime trace (spec
   §31's "lease resolution must be explicit in runtime trace").

## Why `lease_resolver` and not an inline lease list

The runtime never accepts a bare list of "extra capabilities" or lease
ids to trust wholesale (spec §18) — `lease_resolver` is a callable that
must independently decide, per action, which single lease (if any) might
apply; `_try_elevate()` then independently re-validates it from scratch
through `resolve_lease()`. A `lease_resolver` that always returns some
attacker-controlled id gains nothing — an invalid, wrong-tenant, wrong-
scope, expired, or revoked lease id still resolves to DENY.

## Verified end-to-end

`tests/test_godmode_concurrency_and_e2e.py` and
`orca/godmode/eval_harness.py`'s scenario 24 both run a REAL
`AgentGoal -> AgentPlan -> AgentRuntime -> lease resolution -> Policy ->
tool execution -> Observation -> WorldState` chain: an action denied
under empty capabilities completes once a real issued lease is
resolved, and the same setup with a mismatched `tenant_id` stays denied
and is never recorded as elevated.
