# Phase 10.1 — Exact-Action Lease Binding

## The gap found

Phase 10's `GodmodeApproval.arguments_hash` was computed at
`make_approval()` time (via `repr(sorted(arguments.items()))` — itself
the exact unstable-representation anti-pattern this phase's spec
forbids) but:

1. `CapabilityLease` had NO `arguments_hash` field at all — `issue_lease()`
   silently discarded the approval's hash entirely.
2. `resolve_lease()` had no `arguments` parameter and never compared
   anything against a payload binding.

Net effect: an approval/lease issued for one exact action (e.g.
`CONNECTOR_WRITE` on `customer/123` with `{"status": "verified"}`) could
be reused, while otherwise valid, for a materially different argument
payload (e.g. `{"status": "deleted"}`) with zero enforcement — the
production blocker this phase closes.

## Flow (before and after)

```
BEFORE:
GodmodeApproval.arguments_hash  ──X (discarded)──>  CapabilityLease (no field)
                                                          │
                                                          v
                                          resolve_lease() -- no arguments param at all

AFTER:
GodmodeApproval.arguments_hash  ──(copied structurally)──>  CapabilityLease.arguments_hash
                                                                   │ (signed field)
                                                                   v
                                          resolve_lease(..., arguments=<payload>)
                                              -> canonicalize -> hash -> constant-time compare
                                                                   │
                                                                   v
                                          resolve_and_consume_lease()
                                              -> only consumes a use on a FULL match
```

## Where enforcement now happens

- `orca/godmode/resolution.py::resolve_lease()` — the argument check runs
  AFTER scope match, BEFORE the function returns ALLOW. An
  `EXACT_ARGUMENTS` lease with no `arguments` supplied by the caller is
  DENY (never silently skipped).
- `orca/godmode/resolution.py::resolve_and_consume_lease()` — the new
  side-effecting entry point. Runs `resolve_lease()` (including the
  argument check) FIRST; only calls `consume_use()` if that returns
  ALLOW. A failed argument match therefore never burns a use.
- `orca/godmode/policy.py::evaluate_elevated_policy()` and
  `orca/godmode/connector_elevation.py::evaluate_connector_policy_with_elevation()`
  both now call `resolve_and_consume_lease()` (previously bare
  `resolve_lease()`, and previously never consumed a use at all for
  these two domains — a related gap, also fixed, see SECURITY.md).
- `orca/agent/runtime.py::AgentRuntime._try_elevate()` extracts the
  action's PAYLOAD arguments (`action.arguments` minus the
  `resource_scope`/`operation_scope` scope-descriptor keys) and passes
  them through to both `compute_effective_capabilities()` (read-only
  check) and `evaluate_elevated_policy()` (the one call that actually
  consumes).

## Two independent scope dimensions

`resource_scope`/`operation_scope` (already enforced since Phase 10)
remain the lease's COARSE scope — e.g. "this connector instance, this
customer record, this operation name." `arguments_hash` (new in 10.1)
binds the FINE-GRAINED action PAYLOAD — e.g. "the write's actual body."
These are checked independently and both must pass; changing either one
alone is denied (verified in
`tests/test_godmode_exact_argument_binding.py::test_replay_matrix`).
