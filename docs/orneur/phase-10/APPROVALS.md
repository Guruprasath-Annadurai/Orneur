# Phase 10 — Approvals and Issuance Authority

## Issuance authority (spec §9)

`orca.godmode.issuance.issue_lease()` accepts only
`LeaseIssuerClass.HUMAN_APPROVAL` / `SYSTEM_POLICY` / `ADMIN_POLICY` —
any other value raises `LeaseIssuanceError`. There is no code path
anywhere that lets a model, tool output, retrieved content, Memory
record, or Court verdict construct a `GodmodeApproval` or call
`issue_lease()` directly — confirmed both structurally (no
`orca.deliberation`/`orca.society`/`orca.memory`/`orca.truth` module
imports `orca.godmode` at all — see `tests/test_godmode_boundaries.py`)
and functionally (`test_disallowed_issuer_class_rejected`,
`test_model_injection_text_cannot_construct_a_valid_lease`).

## Human approval (spec §10)

`GodmodeApproval` (frozen) binds to the EXACT `principal_id`,
`tenant_id`, `capability_domain`, `capability`, `resource_scope`,
`operation_scope`, `arguments_hash` (canonical SHA-256 of the action's
payload arguments — see EXACT_ACTION_BINDING.md; Phase 10.1 replaced
the original unstable `repr(sorted(...))` with real, deterministic
canonicalization), `duration_s`, `reason`, `approved_by`, and
`binding_mode`. This is the same exact-match discipline as
`orca.connectors.security.ApprovalBinding`, generalized beyond
connectors. `make_approval()` also caps `duration_s` at the same
900-second ceiling `issue_lease()` itself enforces, so an approval
cannot be used to smuggle a longer-lived lease than the platform allows.

**Required invariant (Phase 10.1 spec §6), enforced structurally**:
`lease.arguments_hash == approval.arguments_hash` for an
`EXACT_ARGUMENTS` approval — `issue_lease()`'s signature has no
`arguments_hash` parameter at all, so there is no way for a caller to
supply a different value at issuance; the lease's hash is always copied
directly from the approval it was issued against
(`tests/test_godmode_exact_argument_binding.py::test_issue_lease_does_not_accept_a_caller_supplied_arguments_hash_override`).

## ElevatedCapabilityRequest — proposal only

A model MAY produce an `ElevatedCapabilityRequest` (naming a capability,
resource, operation, reason, duration, risk). This is NEVER sufficient
to activate anything — it is only ever a typed proposal that trusted
platform code (a human reviewing it, or a deterministic system/admin
policy) may choose to approve via `make_approval()` and then issue via
`issue_lease()`. `issue_lease()`'s signature does not even accept an
`ElevatedCapabilityRequest` directly — only a `GodmodeApproval`.

## Approval UX contract (spec §55)

No product UI was built (none exists in this codebase to extend). The
structured contract is `ElevatedCapabilityRequest` itself — it already
carries `capability`, `resource_scope`, `reason`, `requested_duration_s`,
`risk`, and `run_reference`, which is everything a pending-elevation
review surface would need to render "what / why / resource / risk /
duration / requested capability." A future API layer can serialize this
dataclass directly.
