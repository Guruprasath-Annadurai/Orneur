# Phase 10 — Dual-Mode Godmode Architecture

## Canonical rule

```
effective_authority = normal_authority + valid_elevated_lease_scope
```

never `effective_authority = unrestricted`. Every layer below exists to
enforce this literally: there is no code path anywhere in
`orca/godmode/` that computes an "everything" or "admin" capability set.

## Flow

```
AgentAction denied/require-approval by normal Policy Engine
    -> AgentRuntime.lease_resolver(action) -> candidate lease_id (or None)
        -> orca.godmode.capability.compute_effective_capabilities()
            -> orca.godmode.resolution.resolve_lease()  (fail-closed: kill switch,
               existence, integrity, revocation, expiry, uses-remaining,
               tenant, capability, canonical scope match, in that order)
            -> unmodified orca.agent.capability.check_capabilities()
        -> orca.godmode.policy.evaluate_elevated_policy()
            -> unmodified orca.agent.policy.evaluate_policy()  (ALWAYS runs first)
            -> only consults the lease if normal policy was DENY/REQUIRE_APPROVAL
        -> ALLOW only if BOTH capability and policy resolve ALLOW
    -> ActionAuthorization.elevated_action_class = "ELEVATED_ACTION", lease_id=<id>
    -> AgentTrace.elevated_action_ids records it
```

A `CapabilityLease` is only ever produced by
`orca.godmode.issuance.issue_lease()`, which only accepts
`HUMAN_APPROVAL`/`SYSTEM_POLICY`/`ADMIN_POLICY` issuers and structurally
rejects any wildcard capability/resource/operation.

## Package layout (`orca/godmode/`)

| Module | Responsibility |
|---|---|
| `contracts.py` | `AuthorityLevel`, `GodmodeSession`, `CapabilityLease`, `GodmodeApproval`, `ElevatedPolicyDecision`, audit types. No wildcard-representable lease shape. |
| `integrity.py` | HMAC lease signing/verification, reusing `orca.auth.tokens`'s exact pattern. |
| `lease_store.py` | File-backed persistence (restart-safe), atomic `consume_use()`. |
| `kill_switch.py` | File-backed global kill switch, restart-safe, zero model-reachable path. |
| `issuance.py` | `issue_lease()` -- the ONLY function that produces a valid signed lease. |
| `resolution.py` | `resolve_lease()` -- the single fail-closed validator, full decision trace. |
| `capability.py` | Effective-capability computation feeding an UNMODIFIED `check_capabilities()`. |
| `policy.py` | `evaluate_elevated_policy()` wrapping an UNMODIFIED `evaluate_policy()`. |
| `connector_elevation.py` | Wraps Phase 9's `evaluate_connector_policy()` unchanged. |
| `file_elevation.py` | Narrow, symlink-safe, denylist-hardened elevated file writes. |
| `session.py` | `GodmodeSession` lifecycle bookkeeping (holds no authority itself). |
| `delegation.py` | Nondelegable-by-default lease delegation, subset-only. |
| `audit.py` | Tenant-filtered, secret-redacted elevation audit log. |
| `eval_harness.py` | 24 deterministic scenarios (spec §63). |
| `latency_bench.py` | Framework-overhead-only latency measurement (spec §64). |

## What Phase 10 deliberately did NOT modify

`orca.agent.capability.check_capabilities()`, `orca.agent.policy.evaluate_policy()`,
`orca.connectors.policy.evaluate_connector_policy()`, and
`orca.connectors.registry.ConnectorRegistry` are all byte-for-byte
unchanged. Phase 10 is a genuinely additive layer, not a rewrite of
existing authority boundaries — confirmed by the full 1237-test
application suite (Phase 0-9 tests plus Phase 10's own) passing
unchanged.

`orca.agent.runtime.AgentRuntime` gained two new, optional,
default-`None` constructor parameters (`tenant_id`, `lease_resolver`);
every pre-Phase-10 caller is unaffected (verified: not supplying either
means `orca.godmode` is never even imported for that run — see
EVALUATION.md's fast-path proof).
