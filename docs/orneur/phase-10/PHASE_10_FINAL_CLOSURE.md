# Phase 10.1 — Exact-Action Godmode Closure

**Repository**: orca | **Branch**: session-update-2026-08-25
**Starting SHA**: 136ee4e | **Ending SHA**: 4534b75 (+ this closure doc commit)

## The production blocker and its fix

`GodmodeApproval.arguments_hash` was computed (with an unstable
`repr(sorted(...))` hash) but never reached `CapabilityLease` at all, and
`resolve_lease()` had no `arguments` parameter — an approval/lease for
one exact action could be reused for materially different arguments
with zero enforcement. See `EXACT_ACTION_BINDING.md` for the full trace
and fix.

## Related gap also found and fixed

`AgentRuntime` and connector elevation never called `consume_use()` at
all — only `file_elevation.py` did. "One-use" `AGENT`/`CONNECTOR`-domain
leases were never truly single-use in real usage prior to this pass.
Fixed by introducing `resolve_and_consume_lease()` and routing both
`orca.godmode.policy.evaluate_elevated_policy()` and
`orca.godmode.connector_elevation.evaluate_connector_policy_with_elevation()`
through it.

## Test results (fresh, this closure)

| Suite | Result |
|---|---|
| Full application suite (deterministic) | 1262 passed, 0 failed, 40 deselected |
| Authoritative security suite (69 files, deterministic) | 604 passed, 0 failed, 1 deselected |
| Live/integration suite (`-m live_ollama_smoke`, 8 files) | see FINAL REPORT |
| Godmode-specific tests (5 files) | 82 passed, 0 failed |
| Godmode eval harness | 24/24 (100%) |

## What changed

- `orca/godmode/canonical.py` (new): one deterministic argument-hashing
  function.
- `orca/godmode/contracts.py`: `CapabilityLease.arguments_hash`/
  `binding_mode`, `ArgumentBindingMode` enum, `is_argument_binding_consistent()`;
  `ElevatedPolicyDecision.argument_match`/`binding_mode`.
- `orca/godmode/issuance.py`: `arguments_hash_of()` now delegates to the
  canonical hasher; `issue_lease()` structurally copies the approval's
  hash/binding mode onto the lease and rejects an inconsistent
  `EXACT_ARGUMENTS` lease.
- `orca/godmode/integrity.py`: `arguments_hash`/`binding_mode` added to
  the signed field set.
- `orca/godmode/lease_store.py`: persists the two new fields.
- `orca/godmode/resolution.py`: `resolve_lease()` gained `arguments`;
  new `resolve_and_consume_lease()`.
- `orca/godmode/policy.py`, `orca/godmode/capability.py`,
  `orca/godmode/connector_elevation.py`: thread `arguments` through;
  policy/connector-elevation now consume via the new function.
- `orca/godmode/file_elevation.py`: refactored onto
  `resolve_and_consume_lease()` with an explicitly documented,
  deliberately narrow binding (root directory + operation only — never
  path or content, matching spec's own directory-scoped example).
- `orca/agent/runtime.py`: `_try_elevate()` extracts and forwards the
  action's payload arguments.
- `tests/test_godmode_exact_argument_binding.py` (new, 25 tests) +
  updates to `test_godmode_security.py`/`test_godmode_concurrency_and_e2e.py`
  to pass explicit `arguments={}` where the intent was always
  scope-only testing.

## Known limitations (disclosed, not blocking)

1. `PROCESS_EXECUTION` elevation remains intentionally disabled
   (unchanged from Phase 10).
2. FILE-domain leases deliberately do NOT bind file path or content —
   only the root directory and operation. Documented explicitly in
   `file_elevation.py` and `CAPABILITY_LEASES.md` rather than implied to
   be stronger than implemented. A future FILE lease type wanting
   exact-path (not just exact-content) binding could pass
   `{"path": relative_path}` as its `arguments` — not built here, as no
   current caller needs it and spec's own examples are directory-scoped.
3. No lease-validation cache exists (unchanged from Phase 10) — every
   check reads current disk state directly; still sub-millisecond.

## Final audit counters

| Counter | Value |
|---|---|
| UNSCOPED_GODMODE_CAPABILITY | 0 |
| CROSS_TENANT_GODMODE_BYPASS | 0 |
| LEASE_TAMPER_BYPASS | 0 |
| LEASE_EXPIRY_BYPASS | 0 |
| LEASE_REVOCATION_BYPASS | 0 |
| LEASE_REPLAY_BYPASS | 0 |
| LEASE_USE_COUNT_RACE | 0 |
| APPROVAL_SCOPE_BYPASS | 0 |
| ARGUMENT_SCOPE_BYPASS | 0 |
| ARGUMENT_HASH_TAMPER_BYPASS | 0 |
| MISSING_ARGUMENT_BINDING_BYPASS | 0 |
| CANONICALIZATION_BYPASS | 0 |
| KILL_SWITCH_BYPASS | 0 |
| POLICY_BYPASS | 0 |
| ENTITLEMENT_BYPASS | 0 |
| MODEL_LIFECYCLE_BYPASS | 0 |
| DELEGATION_SCOPE_ESCALATION | 0 |
| UNBOUNDED_GODMODE_BUDGET | 0 |
| UNRESTRICTED_SHELL_ELEVATION | 0 |
| RAW_CHAIN_OF_THOUGHT_STORAGE | 0 |

**READY TO ADVANCE TO PHASE 11: YES**
