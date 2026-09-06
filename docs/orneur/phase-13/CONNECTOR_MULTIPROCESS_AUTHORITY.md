# Phase 13.3 — Connector Multiprocess Authority

## What this closes

Phase 13.2's own disclosed residual risk #4: connector elevation shares
the already-proven `resolve_and_consume_lease()` function with file
elevation, but only file elevation had a dedicated multiprocess worker
test. This document reports the result of building and running one for
the connector path specifically, through the real
`evaluate_connector_policy_with_elevation()` entry point rather than by
calling `lease_store` functions directly.

No new provider integrations were built or are needed — this reuses
Phase 9's existing deterministic fake connector/provider
(`orca.connectors.fake_provider`) exclusively. No real SaaS, no external
network calls.

## The anti-false-positive requirement (spec §15)

The spec explicitly warns against a test that appears to prove
"authorization gating limited writes to exactly one" when the real
cause is provider-side idempotency-key deduplication silently absorbing
a second write. This matters here specifically because
`orca.connectors.fake_provider.FakeProviderState` is an in-memory,
per-process dataclass — each spawned worker constructs its own
independent instance, so the two workers in this test's race can never
even see each other's provider-side state, let alone deduplicate against
it. To prove the authorization boundary — not provider idempotency — is
what limits writes to one, each worker writes a distinct marker file
(`{marker_dir}/write-{pid}.marker`) immediately after receiving `ALLOW`
from the real elevation-policy function, **before** calling the
provider's `fake_write()`. Counting marker files after the race is
therefore direct evidence of how many processes crossed the
authorization boundary, entirely independent of what either process's
own provider state does afterward.

## Setup

- One `ConnectorInstance` configuration (`connector_type=TICKETING`,
  `READ_ONLY` base mode, `resource_path="ticket/42"`), constructed
  identically by every worker with an explicit, shared
  `connector_instance_id="fixed-ticketing-instance"` (deliberately fixed
  rather than the dataclass's random default, so every worker's
  `_connector_resource_scope()` computation matches the one lease
  actually issued).
- One `CapabilityLease` for `CONNECTOR_WRITE` / `close`, `max_uses=1`,
  bound to `arguments={"text": "closed"}` via `hash_arguments()` (Phase
  10.1 exact-argument binding).
- Two independent worker processes (`multiprocessing.get_context("spawn")`),
  synchronized to start concurrently via a shared `multiprocessing.Barrier`.
  Both go through the real connector elevation path
  (`evaluate_connector_policy_with_elevation()`), not a direct
  `lease_store` call.

## Core result (spec §13-15)

`test_connector_multiprocess_exactly_one_reaches_privileged_write`:

- Exactly **1** process receives `ALLOW`; the other receives `DENY`
  (lease exhausted).
- The `ALLOW`'d process's `fake_write()` call returns `SUCCESS`.
- Exactly **1** marker file exists after the race — direct,
  provider-independent proof that only one process ever crossed the
  authorization boundary.
- Post-race, `get(lease.lease_id).uses_remaining == 0`.

## Control: wrong-action (spec §16)

`test_connector_wrong_action_process_denies_without_consuming_use`:

- A process attempting the lease's bound arguments (`{"text": "closed"}`)
  is compared against one attempting different arguments
  (`{"text": "deleted"}`), reusing Phase 10.1's exact-argument binding.
- The wrong-argument attempt is **denied**, and critically does **not**
  consume a use — `uses_remaining` is confirmed still `1` immediately
  after.
- The correct-argument attempt, run afterward against the same
  still-live lease, succeeds and consumes the one remaining use
  (`uses_remaining == 0` after).

## Control: wrong-tenant (spec §17)

`test_connector_wrong_tenant_process_denies_without_consuming_use`:

- Same lease (issued for `tenant_id="org-1"`). One attempt uses
  `identity.tenant_id="org-WRONG-TENANT"`, denied without consuming the
  valid use (`uses_remaining` confirmed still `1` afterward).
- The correct-tenant attempt, run afterward, succeeds and consumes the
  use (`uses_remaining == 0` after).

## Race: connector revocation (spec §18 — the one race added)

`test_connector_revocation_race_no_write_after_committed_revocation`:

- A connector-write worker and a `revoke()` worker race concurrently
  (shared `Barrier`, both real spawned processes) against the same
  5-use lease.
- Regardless of which side of the race wins, the post-race durable state
  is confirmed `REVOKED` (`is_revoked() == True`).
- A follow-up connector-write attempt against the now-revoked lease is
  confirmed **denied**.

## Not separately added: connector kill-switch race (spec §19)

Per the spec's own explicit allowance ("one executable connector race
is sufficient if documented" / "do not expand scope excessively if the
existing resolve path already gives strong coverage"), a dedicated
connector-specific kill-switch race was **not** added as a second race
test. Justification: `evaluate_connector_policy_with_elevation()` checks
the kill switch by calling into the exact same `orca.godmode.kill_switch`
/ `orca.godmode.resolution` code path already exercised, with a real
multiprocess race, by Phase 13.2's
`tests/test_godmode_distributed_atomicity.py` kill-switch-race test —
connector elevation adds no additional kill-switch-specific logic on top
of that shared path. The revocation race above already demonstrates that
a connector-specific caller correctly observes a mid-race authority-state
change made by a concurrent process; a kill-switch race would exercise
the identical mechanism through the identical shared function.

## Confirmation: normal connector operations are unaffected (spec §21)

Non-elevated connector reads/writes (`read_write_mode="READ_ONLY"` or
any capability not requiring elevation) never call
`resolve_and_consume_lease()` or touch `orca.godmode.lease_store` at
all — `evaluate_connector_policy_with_elevation()` only reaches the
Godmode SQLite transaction when the requested capability is not already
granted by the connector's own static policy. This is unchanged
structurally from Phase 13.2; Phase 13.3 added no new branch here.

## Test results

`tests/test_connector_multiprocess_authority.py` — **4 passed, 0
failed**: core race, wrong-action control, wrong-tenant control,
revocation race.

## Audit counter

- `CONNECTOR_MULTIPROCESS_DOUBLE_EXECUTION`: **0** — every race
  produced exactly one marker file and exactly one provider-side
  `SUCCESS`, across all four tests.
