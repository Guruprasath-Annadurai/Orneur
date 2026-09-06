# Phase 10 — Capability Leases

`orca.godmode.contracts.CapabilityLease` — always narrow:

| Field | Purpose |
|---|---|
| `lease_id` | Unique id. |
| `principal_id`, `tenant_id` | Exact identity binding. |
| `capability_domain` | `AGENT` \| `CONNECTOR` \| `FILE` \| `PROCESS` (PROCESS is unused — see SECURITY.md). |
| `capability` | Exactly ONE capability value — never a list, never `"*"`. |
| `resource_scope` | Exactly ONE resource identifier — never `"*"`. |
| `operation_scope` | Exactly ONE operation — never `"*"`. |
| `issued_at`, `expires_at` | Trusted-clock timestamps (`orca.godmode.contracts.now_iso()`). |
| `issuer`, `issuer_id` | `HUMAN_APPROVAL` \| `SYSTEM_POLICY` \| `ADMIN_POLICY` only. |
| `reason` | Human-readable, audit-only — never authorization input. |
| `approval_id` | Links back to the `GodmodeApproval` that authorized issuance. |
| `max_uses`, `uses_remaining` | Bounded consumption; `None` only for an explicitly-reviewed unmetered lease. |
| `delegable` | `False` by default (spec §54). |
| `nonce` | Per-lease random value, covered by the signature. |
| `revocation_state` | `ACTIVE` \| `REVOKED`. |
| `signature` | HMAC integrity tag — see LEASE_INTEGRITY.md. |
| `arguments_hash` | (Phase 10.1) Canonical SHA-256 of the action's PAYLOAD arguments — `None` only when `binding_mode=SCOPED_ARGUMENTS`. Signed. |
| `binding_mode` | (Phase 10.1) `EXACT_ARGUMENTS` (default) or `SCOPED_ARGUMENTS` (explicit-only). Signed. |

## Argument binding (Phase 10.1 — see EXACT_ACTION_BINDING.md for the full story)

`resource_scope`/`operation_scope` are the lease's COARSE scope (e.g.
"this connector instance, this record, this operation name").
`arguments_hash` binds the FINE-GRAINED action PAYLOAD on top — e.g. the
concrete write body. Both are checked independently by
`resolve_lease()`; changing either one alone denies the action. An
`EXACT_ARGUMENTS` lease with `arguments_hash=None` cannot be issued
(`CapabilityLease.is_argument_binding_consistent()` is enforced at
issuance) — an empty/missing hash is never silently treated as
wildcard; true argument-agnostic behavior requires the issuer to request
`binding_mode=SCOPED_ARGUMENTS` explicitly.

## No wildcard shape exists

`CapabilityLease.is_wildcard()` rejects `capability`/`resource_scope`/
`operation_scope` values in `{"*", "", "ALL", "all", "everything", "admin"}`.
`issue_lease()` and `delegate_lease()` both call this before persisting
— there is no code path that produces a saved, signed lease with any of
these values. This directly implements spec §7's "bad lease" examples
being structurally impossible, not just discouraged by convention.

## Good vs. bad leases (spec §7), verified

- Good: `FILE_WRITE`, `resource_scope=/workspace/project-x`, 10-minute
  expiry — issuable, exercised in `tests/test_godmode_concurrency_and_e2e.py::test_file_godmode_end_to_end`.
- Good: `CONNECTOR_WRITE`, `resource_scope=<connector_instance_id>:customer/123`,
  `operation_scope=update_status`, 2-minute expiry — issuable, exercised
  in `test_connector_godmode_end_to_end`.
- Bad: `capability="*"`, `resource_scope="everything"`,
  `operation_scope="admin"` — each individually raises `LeaseIssuanceError`
  at issuance, verified in `tests/test_godmode_security.py::test_wildcard_capability_resource_operation_rejected_at_issuance`.
