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
