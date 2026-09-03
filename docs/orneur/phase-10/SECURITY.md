# Phase 10 — Security Summary

## Threat coverage

| Threat | Mitigation | Verified in |
|---|---|---|
| Lease tampering (expiry/capability/tenant/resource/operation/issuer) | HMAC signature over all of these fields; any change fails `verify_lease_integrity()` | `test_godmode_security.py` |
| Nonce reuse | Signature covers nonce; copying it onto a different lease still fails integrity | `test_godmode_security.py` |
| Model/user/tool injection ("you are in Godmode now", "give yourself an admin lease") | `issue_lease()` only accepts a `GodmodeApproval` object built by trusted code; a bare string raises `AttributeError`/`TypeError` | `test_godmode_security.py` |
| Wildcard lease ("everything", "admin", "*") | Structurally rejected at issuance (`is_wildcard()`) | `test_godmode_security.py` |
| Untrusted issuer (model/Court/tool as issuer) | `issue_lease()` only accepts the 3 trusted `LeaseIssuerClass` values | `test_godmode_security.py`, `test_godmode_boundaries.py` |
| Approval forgery (fake id, wrong args, expired) | Approval binds exact capability/resource/operation/argument-hash; the LEASE's own scope (not the approval) is what `resolve_lease()` checks, so a forged "matching" approval still can't widen an already-issued lease's scope | `test_godmode_security.py` |
| Scope confusion (case, trailing slash, dot-segments, prefix abuse) | Canonical normalization in `resolve_lease()`'s `_canonicalize()`; prefix abuse (`project-x` vs `project-x-evil`) never matches | `test_godmode_security.py` |
| Connector resource aliasing across instances | `resource_scope` always embeds `connector_instance_id` | `test_godmode_security.py` |
| Clock skew / future-issued token | Trusted-clock-only (`now_iso()`); a tampered `issued_at` fails integrity separately | `test_godmode_security.py` |
| Revocation under cache | No cache exists in front of `resolve_lease()` — always reads current disk state | `test_godmode_security.py` |
| Kill switch bypass | Checked first in `resolve_lease()`; never reachable from agent tool code (AST-verified) | `test_godmode_security.py` |
| Unbounded/negative/reset budget | No `orca/godmode/*.py` file references `CognitiveBudget` consumption fields at all — elevated actions share the exact same `AgentRuntime`/`SocietyBudgetLedger` reservation path as normal actions | `test_godmode_security.py` |
| Concurrent one-use-lease race (TOCTOU) | Per-lease-id `threading.Lock` around `consume_use()` | `test_godmode_concurrency_and_e2e.py` (8 real threads, exactly 1 succeeds) |
| Delegation scope escalation | `delegate_lease()` rejects non-delegable parent (default), wider expiry, or excess uses | `test_godmode_delegation` coverage in eval harness + `orca/godmode/delegation.py`'s own error paths |
| Filesystem path traversal / symlink escape | Reuses `orca.tools._resolve_in_workspace`'s realpath-resolution discipline, generalized; hard-coded denylist (`/etc`, `/root`, `~/.ssh`, `~/.aws`, `~/.gnupg`, `auth.db`, godmode's own store) | `test_godmode_concurrency_and_e2e.py::test_file_godmode_end_to_end` |
| Cross-tenant elevation | Checked in the base Policy/Connector-Policy Engine AND independently in `resolve_lease()` — two layers | `test_godmode_boundaries.py`, e2e tests |

## Structural (not just behavioral) guarantees

- `CapabilityLease` has no field shaped like an entitlement/model-tier/
  epistemic override, and `CapabilityDomain` has no `MEMORY` or
  `MODEL_LIFECYCLE` value — there is no REPRESENTABLE lease that could
  touch those systems, not merely a runtime check that happens to
  refuse it.
- No file under `orca/deliberation/`, `orca/society/`, `orca/memory/`,
  `orca/truth/`, `orca/cognitive/entitlement.py`,
  `orca/registry/model_spec.py`, or `orca/gateway/wiring.py` imports
  `orca.godmode` at all (AST-verified across all of them).
- `orca.agent.capability.check_capabilities()` and
  `orca.agent.policy.evaluate_policy()` are byte-for-byte unchanged from
  Phase 8 — Phase 10 never modified the functions that define "normal
  authority," only added a layer that computes what to feed them.

## Real bug found and fixed during this phase

`tests/test_godmode_fast_path.py`'s original fast-path proof deleted
`orca.godmode.*` entries from `sys.modules` to verify they weren't
imported on a normal run — this broke `tests/conftest.py`'s autouse
lease-store/kill-switch isolation fixture for every LATER test in the
same pytest session (a fresh re-import creates a new module object whose
`LEASE_DIR` reverts to the real, unpatched `ORCA_HOME`). Confirmed via
direct evidence: 37 real lease files leaked into the developer's actual
`~/.orca/godmode/leases/` during a combined test run. Fixed with a
non-destructive `sys.modules` snapshot-diff check instead, and the
leaked directory was removed. Re-verified: a full 1237-test run leaves
zero trace under the real `~/.orca/godmode/`.

## Disclosed, non-fabricated limitations

1. `PROCESS_EXECUTION` elevation is intentionally NOT implemented (spec
   §62 explicitly permits leaving it disabled when the architecture
   can't yet safely support it) — no `orca/godmode/process_elevation.py`
   exists. `CapabilityDomain.PROCESS` is defined in the enum for future
   use but nothing constructs a lease with it today.
2. No cache exists for lease validation (see REVOCATION.md) — this is a
   simplicity choice (no cache to key/invalidate), not a gap, but it
   means every `resolve_lease()` call does a real file read; latency
   numbers in EVALUATION.md reflect this honestly (still sub-millisecond).
3. Lease integrity is HMAC (symmetric, matching this codebase's existing
   pattern), not an asymmetric signature — this is disclosed explicitly
   in LEASE_INTEGRITY.md rather than implied to be a stronger guarantee
   than it is.
