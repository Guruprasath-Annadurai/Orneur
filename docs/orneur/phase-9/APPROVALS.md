# Phase 9 — Approval Binding

`orca.connectors.security.ApprovalBinding` (frozen) binds an approval to
the EXACT `connector_instance_id`, `resource_scope`, `operation`, and a
SHA-256 hash of the sorted arguments (`arguments_hash`) plus an
`expires_at` -- never a vague "yes, do anything."

## Matching semantics

`ApprovalBinding.matches(connector_instance_id, resource_scope,
operation, arguments)` requires ALL fields to match exactly, including
re-hashing the supplied `arguments` and comparing against
`arguments_hash`. Changing ANY bound field -- including a single argument
value -- invalidates the approval outright. Verified directly:
`test_approval_binding_rejects_changed_arguments_forgery` (attacker
reuses a valid approval with swapped argument payload -> rejected) and
`test_approval_binding_rejects_replay_on_different_connector` (attacker
reuses a valid approval against a different connector instance ->
rejected).

## Expiry

`is_expired(binding, now_iso)` is a simple ISO-8601 string comparison
against `expires_at` -- an expired binding is never treated as valid
regardless of how well its other fields match.

## Where approval fits in the flow

`orca.connectors.policy.evaluate_connector_policy()` returns
`REQUIRE_APPROVAL` for SENSITIVE-data writes/deletes. The calling
platform code is responsible for obtaining human approval and
constructing an `ApprovalBinding` before retrying the connector action;
`ApprovalBinding` itself does not automatically re-invoke the policy
engine -- it is the artifact a caller checks before allowing a
previously-REQUIRE_APPROVAL action to proceed.
