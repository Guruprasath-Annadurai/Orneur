"""
Phase 10.1 — exact-action lease binding + approval/lease integrity
closure. Closes the production blocker: GodmodeApproval.arguments_hash
was recorded but never enforced by resolve_lease() during actual
elevated-action authorization.
"""
from __future__ import annotations

import threading

import pytest

from orca.connectors.contracts import ConnectorCapabilityKind, ConnectorIdentity, ConnectorInstance, ConnectorType
from orca.godmode.canonical import canonicalize_arguments, hash_arguments
from orca.godmode.connector_elevation import evaluate_connector_policy_with_elevation
from orca.godmode.contracts import ArgumentBindingMode, CapabilityDomain, ElevatedCapabilityRequest, LeaseIssuanceError, LeaseIssuerClass
from orca.godmode.integrity import apply_signature, verify_lease_integrity
from orca.godmode.issuance import issue_lease, make_approval
from orca.godmode.lease_store import get as get_lease, save
from orca.godmode.resolution import resolve_and_consume_lease, resolve_lease


def _issue_connector_lease(*, resource="conn-1:customer/123", operation="update_status", arguments=None, tenant_id="org-1", max_uses=1, binding_mode=ArgumentBindingMode.EXACT_ARGUMENTS):
    req = ElevatedCapabilityRequest(principal_id="u1", tenant_id=tenant_id, capability_domain=CapabilityDomain.CONNECTOR, capability="CONNECTOR_WRITE", resource_scope=resource, operation_scope=operation, reason="test")
    approval = make_approval(request=req, approved_by="human-1", duration_s=120, arguments=arguments, binding_mode=binding_mode)
    return issue_lease(approval=approval, issuer=LeaseIssuerClass.HUMAN_APPROVAL, issuer_id="human-1", max_uses=max_uses)


def _instance(tenant_id="org-1", instance_id="conn-1"):
    return ConnectorInstance(
        connector_instance_id=instance_id, connector_type=ConnectorType.TICKETING, tenant_id=tenant_id, owner_principal_id="u1",
        read_write_mode="READ_ONLY", enabled_capabilities=frozenset({ConnectorCapabilityKind.CONNECTOR_READ}),
    )


# ── canonical hashing (spec §3-4) ────────────────────────────────────────

def test_canonical_hash_stable_across_key_order():
    assert hash_arguments({"a": 1, "b": 2}) == hash_arguments({"b": 2, "a": 1})


def test_canonical_hash_stable_across_nested_key_order():
    assert hash_arguments({"outer": {"a": 1, "b": 2}}) == hash_arguments({"outer": {"b": 2, "a": 1}})


def test_canonical_hash_distinguishes_int_and_float():
    assert hash_arguments({"n": 2}) != hash_arguments({"n": 2.0})


def test_canonical_hash_distinguishes_bool_and_int():
    assert hash_arguments({"flag": True}) != hash_arguments({"flag": 1})


def test_canonical_hash_preserves_list_order():
    assert hash_arguments({"items": [1, 2, 3]}) != hash_arguments({"items": [3, 2, 1]})


def test_canonical_hash_unicode_nfc_nfd_equal():
    nfc = {"name": "café"}       # é as single codepoint
    nfd = {"name": "café"}      # e + combining acute accent
    assert hash_arguments(nfc) == hash_arguments(nfd)


def test_canonical_hash_rejects_unstable_str_dict_style():
    """We must never fall back to str(dict)/repr(sorted(...)) -- verify
    the canonical representation is real JSON, not a repr string."""
    canonical = canonicalize_arguments({"a": 1})
    assert canonical.startswith("{") and "__t" in canonical


# ── connector exact scenario (spec §11) ──────────────────────────────────

def test_connector_write_approved_status_verified_denies_status_deleted():
    """Exact spec §11 scenario: approved {'status':'verified'}, attempted
    {'status':'deleted'} on the SAME connector/tenant/resource/operation
    -> DENY."""
    lease = _issue_connector_lease(arguments={"status": "verified"})
    identity = ConnectorIdentity(tenant_id="org-1", principal_id="u1")
    instance = _instance(instance_id="conn-1")

    matching = evaluate_connector_policy_with_elevation(
        identity=identity, instance=instance, requested_capability=ConnectorCapabilityKind.CONNECTOR_WRITE,
        resource="customer/123", operation="update_status", lease_id=lease.lease_id, arguments={"status": "verified"},
    )
    assert matching.state.value == "ALLOW"


def test_connector_write_approved_status_verified_denies_status_deleted_separate_lease():
    lease = _issue_connector_lease(arguments={"status": "verified"})
    identity = ConnectorIdentity(tenant_id="org-1", principal_id="u1")
    instance = _instance(instance_id="conn-1")

    mismatched = evaluate_connector_policy_with_elevation(
        identity=identity, instance=instance, requested_capability=ConnectorCapabilityKind.CONNECTOR_WRITE,
        resource="customer/123", operation="update_status", lease_id=lease.lease_id, arguments={"status": "deleted"},
    )
    assert mismatched.state.value == "DENY"
    # the failed match must NOT have consumed the lease's use
    assert get_lease(lease.lease_id).uses_remaining == 1


def test_connector_write_missing_arguments_denies():
    """spec §9: if the lease requires exact action binding and the
    runtime does not supply current arguments: DENY."""
    lease = _issue_connector_lease(arguments={"status": "verified"})
    identity = ConnectorIdentity(tenant_id="org-1", principal_id="u1")
    instance = _instance(instance_id="conn-1")

    decision = evaluate_connector_policy_with_elevation(
        identity=identity, instance=instance, requested_capability=ConnectorCapabilityKind.CONNECTOR_WRITE,
        resource="customer/123", operation="update_status", lease_id=lease.lease_id,
        # arguments intentionally omitted
    )
    assert decision.state.value == "DENY"


# ── lease contract invariant (spec §6) ───────────────────────────────────

def test_issued_lease_arguments_hash_equals_approval_arguments_hash():
    req = ElevatedCapabilityRequest(principal_id="u1", tenant_id="org-1", capability_domain=CapabilityDomain.CONNECTOR, capability="CONNECTOR_WRITE", resource_scope="conn-1:customer/123", operation_scope="update_status", reason="test")
    approval = make_approval(request=req, approved_by="human-1", duration_s=60, arguments={"status": "verified"})
    lease = issue_lease(approval=approval, issuer=LeaseIssuerClass.HUMAN_APPROVAL, issuer_id="human-1")
    assert lease.arguments_hash == approval.arguments_hash


def test_issue_lease_does_not_accept_a_caller_supplied_arguments_hash_override():
    """issue_lease()'s signature has no arguments_hash parameter at all
    -- structurally, a caller cannot replace the approval's binding
    during issuance."""
    import inspect
    from orca.godmode.issuance import issue_lease as il
    sig = inspect.signature(il)
    assert "arguments_hash" not in sig.parameters


# ── integrity (spec §7, §17) ──────────────────────────────────────────────

def test_arguments_hash_tampering_fails_integrity():
    lease = _issue_connector_lease(arguments={"status": "verified"})
    lease.arguments_hash = hash_arguments({"status": "deleted"})
    assert verify_lease_integrity(lease) is False


def test_binding_mode_tampering_fails_integrity():
    lease = _issue_connector_lease(arguments={"status": "verified"})
    lease.binding_mode = ArgumentBindingMode.SCOPED_ARGUMENTS
    assert verify_lease_integrity(lease) is False


def test_exact_arguments_lease_requires_nonempty_hash_at_issuance():
    """A hand-crafted (never through issue_lease) EXACT_ARGUMENTS lease
    with no hash is structurally inconsistent."""
    from orca.godmode.contracts import CapabilityLease
    lease = CapabilityLease(capability_domain=CapabilityDomain.CONNECTOR, capability="CONNECTOR_WRITE", resource_scope="x", operation_scope="y", binding_mode=ArgumentBindingMode.EXACT_ARGUMENTS, arguments_hash=None)
    assert lease.is_argument_binding_consistent() is False


# ── SCOPED_ARGUMENTS is explicit, never a default (spec §13) ─────────────

def test_scoped_arguments_must_be_explicitly_requested():
    req = ElevatedCapabilityRequest(principal_id="u1", tenant_id="org-1", capability_domain=CapabilityDomain.FILE, capability="FILE_WRITE", resource_scope="/tmp/x", operation_scope="write", reason="test")
    default_approval = make_approval(request=req, approved_by="human-1", duration_s=60)
    assert default_approval.binding_mode == ArgumentBindingMode.EXACT_ARGUMENTS

    scoped_approval = make_approval(request=req, approved_by="human-1", duration_s=60, binding_mode=ArgumentBindingMode.SCOPED_ARGUMENTS)
    lease = issue_lease(approval=scoped_approval, issuer=LeaseIssuerClass.HUMAN_APPROVAL, issuer_id="human-1")
    assert lease.binding_mode == ArgumentBindingMode.SCOPED_ARGUMENTS
    assert lease.arguments_hash is None

    decision = resolve_lease(lease.lease_id, tenant_id="org-1", capability_domain=CapabilityDomain.FILE, capability="FILE_WRITE", resource_scope="/tmp/x", operation_scope="write")
    assert decision.state.value == "ALLOW"  # SCOPED_ARGUMENTS: no arguments needed at all


def test_scoped_arguments_lease_still_enforces_scope():
    req = ElevatedCapabilityRequest(principal_id="u1", tenant_id="org-1", capability_domain=CapabilityDomain.FILE, capability="FILE_WRITE", resource_scope="/tmp/x", operation_scope="write", reason="test")
    approval = make_approval(request=req, approved_by="human-1", duration_s=60, binding_mode=ArgumentBindingMode.SCOPED_ARGUMENTS)
    lease = issue_lease(approval=approval, issuer=LeaseIssuerClass.HUMAN_APPROVAL, issuer_id="human-1")
    decision = resolve_lease(lease.lease_id, tenant_id="org-1", capability_domain=CapabilityDomain.FILE, capability="FILE_WRITE", resource_scope="/tmp/OTHER", operation_scope="write")
    assert decision.state.value == "DENY"


# ── use-consumption ordering (spec §18-19) ────────────────────────────────

def test_failed_argument_match_never_consumes_a_use():
    lease = _issue_connector_lease(arguments={"status": "verified"}, max_uses=1)
    identity = ConnectorIdentity(tenant_id="org-1", principal_id="u1")
    instance = _instance(instance_id="conn-1")

    for _ in range(3):
        decision = evaluate_connector_policy_with_elevation(
            identity=identity, instance=instance, requested_capability=ConnectorCapabilityKind.CONNECTOR_WRITE,
            resource="customer/123", operation="update_status", lease_id=lease.lease_id, arguments={"status": "WRONG"},
        )
        assert decision.state.value == "DENY"
    assert get_lease(lease.lease_id).uses_remaining == 1

    ok = evaluate_connector_policy_with_elevation(
        identity=identity, instance=instance, requested_capability=ConnectorCapabilityKind.CONNECTOR_WRITE,
        resource="customer/123", operation="update_status", lease_id=lease.lease_id, arguments={"status": "verified"},
    )
    assert ok.state.value == "ALLOW"
    assert get_lease(lease.lease_id).uses_remaining == 0


def test_resolve_and_consume_lease_is_atomic_only_correct_argument_competitor_wins():
    """spec §18: changed-argument competitor must not consume the valid
    lease's use count if resolution fails before consumption -- verified
    with real concurrent threads, one with the CORRECT arguments and
    several with WRONG arguments, racing a one-use lease."""
    lease = _issue_connector_lease(arguments={"status": "verified"}, max_uses=1)
    results = []
    barrier = threading.Barrier(6)

    def _attempt(args):
        barrier.wait()
        decision = resolve_and_consume_lease(
            lease.lease_id, tenant_id="org-1", capability_domain=CapabilityDomain.CONNECTOR, capability="CONNECTOR_WRITE",
            resource_scope="conn-1:customer/123", operation_scope="update_status", arguments=args,
        )
        results.append((args, decision.state.value))

    threads = [threading.Thread(target=_attempt, args=({"status": "verified"},))]
    threads += [threading.Thread(target=_attempt, args=({"status": "WRONG"},)) for _ in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    allows = [r for r in results if r[1] == "ALLOW"]
    assert len(allows) == 1
    assert allows[0][0] == {"status": "verified"}
    assert get_lease(lease.lease_id).uses_remaining == 0


# ── argument normalization security (spec §14-15) ─────────────────────────

def test_dict_key_reordering_still_matches():
    lease = _issue_connector_lease(arguments={"status": "verified", "priority": "high"})
    identity = ConnectorIdentity(tenant_id="org-1", principal_id="u1")
    instance = _instance(instance_id="conn-1")
    decision = evaluate_connector_policy_with_elevation(
        identity=identity, instance=instance, requested_capability=ConnectorCapabilityKind.CONNECTOR_WRITE,
        resource="customer/123", operation="update_status", lease_id=lease.lease_id,
        arguments={"priority": "high", "status": "verified"},  # reordered
    )
    assert decision.state.value == "ALLOW"


def test_numeric_type_confusion_denied():
    lease = _issue_connector_lease(arguments={"amount": 100})
    identity = ConnectorIdentity(tenant_id="org-1", principal_id="u1")
    instance = _instance(instance_id="conn-1")
    decision = evaluate_connector_policy_with_elevation(
        identity=identity, instance=instance, requested_capability=ConnectorCapabilityKind.CONNECTOR_WRITE,
        resource="customer/123", operation="update_status", lease_id=lease.lease_id,
        arguments={"amount": 100.0},  # float instead of int
    )
    assert decision.state.value == "DENY"


def test_boolean_string_confusion_denied():
    lease = _issue_connector_lease(arguments={"urgent": True})
    identity = ConnectorIdentity(tenant_id="org-1", principal_id="u1")
    instance = _instance(instance_id="conn-1")
    decision = evaluate_connector_policy_with_elevation(
        identity=identity, instance=instance, requested_capability=ConnectorCapabilityKind.CONNECTOR_WRITE,
        resource="customer/123", operation="update_status", lease_id=lease.lease_id,
        arguments={"urgent": "true"},
    )
    assert decision.state.value == "DENY"


def test_extra_ignored_field_denied():
    """An attacker cannot slip an extra field past the hash by claiming
    it's 'just extra, discarded at execution' -- the hash covers the
    FULL normalized payload actually supplied to resolution."""
    lease = _issue_connector_lease(arguments={"status": "verified"})
    identity = ConnectorIdentity(tenant_id="org-1", principal_id="u1")
    instance = _instance(instance_id="conn-1")
    decision = evaluate_connector_policy_with_elevation(
        identity=identity, instance=instance, requested_capability=ConnectorCapabilityKind.CONNECTOR_WRITE,
        resource="customer/123", operation="update_status", lease_id=lease.lease_id,
        arguments={"status": "verified", "extra_field": "sneaky"},
    )
    assert decision.state.value == "DENY"


def test_nested_object_reordering_still_matches():
    lease = _issue_connector_lease(arguments={"payload": {"a": 1, "b": 2}})
    identity = ConnectorIdentity(tenant_id="org-1", principal_id="u1")
    instance = _instance(instance_id="conn-1")
    decision = evaluate_connector_policy_with_elevation(
        identity=identity, instance=instance, requested_capability=ConnectorCapabilityKind.CONNECTOR_WRITE,
        resource="customer/123", operation="update_status", lease_id=lease.lease_id,
        arguments={"payload": {"b": 2, "a": 1}},
    )
    assert decision.state.value == "ALLOW"


# ── replay re-run (spec §16) ───────────────────────────────────────────────

def test_replay_matrix():
    lease = _issue_connector_lease(arguments={"status": "verified"}, max_uses=2)
    identity = ConnectorIdentity(tenant_id="org-1", principal_id="u1")
    instance = _instance(instance_id="conn-1")

    same = evaluate_connector_policy_with_elevation(identity=identity, instance=instance, requested_capability=ConnectorCapabilityKind.CONNECTOR_WRITE, resource="customer/123", operation="update_status", lease_id=lease.lease_id, arguments={"status": "verified"})
    assert same.state.value == "ALLOW"

    changed_args = evaluate_connector_policy_with_elevation(identity=identity, instance=instance, requested_capability=ConnectorCapabilityKind.CONNECTOR_WRITE, resource="customer/123", operation="update_status", lease_id=lease.lease_id, arguments={"status": "deleted"})
    assert changed_args.state.value == "DENY"

    changed_resource = evaluate_connector_policy_with_elevation(identity=identity, instance=instance, requested_capability=ConnectorCapabilityKind.CONNECTOR_WRITE, resource="customer/999", operation="update_status", lease_id=lease.lease_id, arguments={"status": "verified"})
    assert changed_resource.state.value == "DENY"

    changed_operation = evaluate_connector_policy_with_elevation(identity=identity, instance=instance, requested_capability=ConnectorCapabilityKind.CONNECTOR_WRITE, resource="customer/123", operation="delete", lease_id=lease.lease_id, arguments={"status": "verified"})
    assert changed_operation.state.value == "DENY"

    bad_tenant_identity = ConnectorIdentity(tenant_id="org-EVIL", principal_id="attacker")
    changed_tenant = evaluate_connector_policy_with_elevation(identity=bad_tenant_identity, instance=instance, requested_capability=ConnectorCapabilityKind.CONNECTOR_WRITE, resource="customer/123", operation="update_status", lease_id=lease.lease_id, arguments={"status": "verified"})
    assert changed_tenant.state.value == "DENY"

    # second legitimate use consumes the last remaining use
    second = evaluate_connector_policy_with_elevation(identity=identity, instance=instance, requested_capability=ConnectorCapabilityKind.CONNECTOR_WRITE, resource="customer/123", operation="update_status", lease_id=lease.lease_id, arguments={"status": "verified"})
    assert second.state.value == "ALLOW"

    exhausted = evaluate_connector_policy_with_elevation(identity=identity, instance=instance, requested_capability=ConnectorCapabilityKind.CONNECTOR_WRITE, resource="customer/123", operation="update_status", lease_id=lease.lease_id, arguments={"status": "verified"})
    assert exhausted.state.value == "DENY"
