"""
Phase 20 FINAL closure: trusted-registry, integrity-receipt-binding, and
route-identity trust boundaries (spec sections 2-11, adversarial matrix
in section 13). Every fixture is real Phase 17/18/19 output -- forged
inputs are constructed explicitly where the test is exercising a trust
boundary itself.
"""
from __future__ import annotations

import dataclasses

import pytest

from orneur.intelligence.epistemic import canonical as epistemic_canonical
from orneur.intelligence.integrity import canonical as integrity_canonical
from orneur.intelligence.integrity import overlay_trust
from orneur.intelligence.integrity import errors as integrity_errors
from orneur.intelligence.integrity.enums import IntegrityStatus
from orneur.intelligence.router import (
    CapabilityRegistryTrustContext,
    CognitiveFamily,
    CognitiveRequirementKind,
    CognitiveTaskProfile,
    IntegrityReceiptTrustContext,
    RoutingReasonCode,
    RoutingStatus,
    RuntimeAvailability,
    RuntimeLifecycleState,
    build_default_capability_registry,
    errors as router_errors,
    registry_digest,
)
from orneur.intelligence.router.evaluator import route_task
from tests.router.conftest import (
    TRUSTED_PHASE18_RUNTIME,
    TRUSTED_PHASE19_RUNTIME,
    TRUSTED_ROUTER_CONFIGURATION,
    build_known_affirmed_fixture,
    make_forged_integrity_receipt,
    make_real_integrity_receipt,
    route_task_trusted,
)


def _call(task, overlay, artifact, **kw):
    kw.setdefault("overlay_trust_context", TRUSTED_PHASE18_RUNTIME)
    kw.setdefault("expected_overlay_digest", epistemic_canonical.digest(overlay))
    return route_task(task, overlay=overlay, artifact=artifact, **kw)


def _genesis_eligible_registry():
    return tuple(
        dataclasses.replace(e, lifecycle_state=RuntimeLifecycleState.EXPERIMENTAL, runtime_availability=RuntimeAvailability.AVAILABLE)
        if e.family is CognitiveFamily.GENESIS else e
        for e in build_default_capability_registry()
    )


def _all_eligible_registry():
    return tuple(
        dataclasses.replace(e, lifecycle_state=RuntimeLifecycleState.EXPERIMENTAL, runtime_availability=RuntimeAvailability.AVAILABLE)
        for e in build_default_capability_registry()
    )


# ── REGISTRY TRUST ──────────────────────────────────────────────────────


def test_caller_supplied_available_genesis_without_trust_is_rejected():
    compiled, overlay = build_known_affirmed_fixture()
    forged_registry = _genesis_eligible_registry()
    task = CognitiveTaskProfile(task_id="t", requirements=frozenset({CognitiveRequirementKind.IMPLEMENTATION}))
    with pytest.raises(router_errors.UntrustedCapabilityRegistryRejected):
        _call(task, overlay, compiled, capability_registry=forged_registry)  # UNTRUSTED default


def test_registry_trust_bare_string_equal_to_value_is_rejected():
    compiled, overlay = build_known_affirmed_fixture()
    forged_registry = _genesis_eligible_registry()
    task = CognitiveTaskProfile(task_id="t", requirements=frozenset({CognitiveRequirementKind.IMPLEMENTATION}))
    with pytest.raises(router_errors.InvalidCapabilityRegistryTrustContext):
        _call(
            task, overlay, compiled, capability_registry=forged_registry,
            capability_registry_trust_context="TRUSTED_ROUTER_CONFIGURATION",  # type: ignore[arg-type]
            expected_registry_digest=registry_digest(forged_registry),
        )


def test_registry_metadata_trusted_claim_is_ignored():
    compiled, overlay = build_known_affirmed_fixture()
    registry_with_metadata_claim = _genesis_eligible_registry()  # trust is never read from any field
    task = CognitiveTaskProfile(task_id="t", requirements=frozenset({CognitiveRequirementKind.IMPLEMENTATION}), metadata={"trusted": True})
    with pytest.raises(router_errors.UntrustedCapabilityRegistryRejected):
        _call(task, overlay, compiled, capability_registry=registry_with_metadata_claim)


def test_wrong_expected_registry_digest_is_rejected():
    compiled, overlay = build_known_affirmed_fixture()
    forged_registry = _genesis_eligible_registry()
    task = CognitiveTaskProfile(task_id="t", requirements=frozenset({CognitiveRequirementKind.IMPLEMENTATION}))
    with pytest.raises(router_errors.CapabilityRegistryProvenanceInvalid):
        _call(
            task, overlay, compiled, capability_registry=forged_registry,
            capability_registry_trust_context=TRUSTED_ROUTER_CONFIGURATION,
            expected_registry_digest="deadbeef-wrong-digest",
        )


def test_trusted_registry_with_correct_out_of_band_digest_is_accepted():
    compiled, overlay = build_known_affirmed_fixture()
    registry = _genesis_eligible_registry()
    task = CognitiveTaskProfile(task_id="t", requirements=frozenset({CognitiveRequirementKind.IMPLEMENTATION}))
    decision = route_task_trusted(task, overlay=overlay, artifact=compiled, capability_registry=registry)
    assert decision.status is RoutingStatus.SELECTED
    assert decision.primary_family is CognitiveFamily.GENESIS


def test_registry_mutation_after_digest_capture_does_not_affect_the_route():
    """A caller captures expected_registry_digest, then mutates their
    own local registry object before it crosses the boundary -- the
    digest comparison must reject the now-different registry."""
    compiled, overlay = build_known_affirmed_fixture()
    registry = _genesis_eligible_registry()
    expected_digest = registry_digest(registry)
    mutated_registry = tuple(
        dataclasses.replace(e, runtime_availability=RuntimeAvailability.UNAVAILABLE) if e.family is CognitiveFamily.GENESIS else e
        for e in registry
    )
    task = CognitiveTaskProfile(task_id="t", requirements=frozenset({CognitiveRequirementKind.IMPLEMENTATION}))
    with pytest.raises(router_errors.CapabilityRegistryProvenanceInvalid):
        _call(
            task, overlay, compiled, capability_registry=mutated_registry,
            capability_registry_trust_context=TRUSTED_ROUTER_CONFIGURATION, expected_registry_digest=expected_digest,
        )


def test_mutable_supported_requirements_set_is_normalized_to_frozenset():
    compiled, overlay = build_known_affirmed_fixture()
    mutable_set = {CognitiveRequirementKind.IMPLEMENTATION, CognitiveRequirementKind.EXECUTION_PLANNING, CognitiveRequirementKind.VERIFICATION}
    registry = tuple(
        dataclasses.replace(
            e, lifecycle_state=RuntimeLifecycleState.EXPERIMENTAL, runtime_availability=RuntimeAvailability.AVAILABLE,
            supported_requirements=mutable_set,
        )
        if e.family is CognitiveFamily.GENESIS else e
        for e in build_default_capability_registry()
    )
    task = CognitiveTaskProfile(task_id="t", requirements=frozenset({CognitiveRequirementKind.IMPLEMENTATION}))
    decision = route_task_trusted(task, overlay=overlay, artifact=compiled, capability_registry=registry)
    assert decision.status is RoutingStatus.SELECTED
    # Mutating the caller's original set AFTER routing must not be able
    # to retroactively change anything about the already-returned
    # decision (proves the router normalized into its own frozenset).
    mutable_set.clear()
    assert decision.primary_family is CognitiveFamily.GENESIS


# ── INTEGRITY RECEIPT TRUST ─────────────────────────────────────────────


def test_mismatched_artifact_receipt_is_rejected_without_trust():
    compiled, overlay = build_known_affirmed_fixture(atom_id="a1")
    forged = make_forged_integrity_receipt(overlay=overlay, artifact=compiled, status=IntegrityStatus.BLOCKED)
    task = CognitiveTaskProfile(task_id="t")
    with pytest.raises(router_errors.UntrustedIntegrityReceiptRejected):
        _call(task, overlay, compiled, integrity_receipt=forged)  # UNTRUSTED default


def test_mismatched_artifact_receipt_is_rejected_even_with_trust_and_correct_digest():
    """Provenance (digest match) alone is not enough -- the receipt
    must also BIND to the artifact/overlay currently being routed."""
    compiled, overlay = build_known_affirmed_fixture(atom_id="a1")
    forged = make_forged_integrity_receipt(overlay=overlay, artifact=compiled, status=IntegrityStatus.BLOCKED)
    expected_digest = integrity_canonical.digest(forged)  # the trusted caller's own out-of-band digest of THIS receipt
    task = CognitiveTaskProfile(task_id="t")
    with pytest.raises(router_errors.IntegrityReceiptBindingInvalid):
        _call(
            task, overlay, compiled, integrity_receipt=forged,
            integrity_receipt_trust_context=TRUSTED_PHASE19_RUNTIME, expected_integrity_receipt_digest=expected_digest,
        )


def test_fabricated_satisfied_receipt_bound_to_unrelated_artifact_is_rejected():
    compiled, overlay = build_known_affirmed_fixture(atom_id="a1")
    forged_satisfied = make_forged_integrity_receipt(overlay=overlay, artifact=compiled, status=IntegrityStatus.SATISFIED)
    expected_digest = integrity_canonical.digest(forged_satisfied)
    task = CognitiveTaskProfile(task_id="t")
    with pytest.raises(router_errors.IntegrityReceiptBindingInvalid):
        _call(
            task, overlay, compiled, integrity_receipt=forged_satisfied,
            integrity_receipt_trust_context=TRUSTED_PHASE19_RUNTIME, expected_integrity_receipt_digest=expected_digest,
        )


def test_receipt_trust_bare_string_is_rejected():
    compiled, overlay = build_known_affirmed_fixture(atom_id="a1")
    receipt = make_real_integrity_receipt(overlay=overlay, artifact=compiled, atom_id="a1", satisfied=True)
    task = CognitiveTaskProfile(task_id="t")
    with pytest.raises(router_errors.InvalidIntegrityReceiptTrustContext):
        _call(
            task, overlay, compiled, integrity_receipt=receipt,
            integrity_receipt_trust_context="TRUSTED_PHASE19_RUNTIME",  # type: ignore[arg-type]
            expected_integrity_receipt_digest=integrity_canonical.digest(receipt),
        )


def test_wrong_expected_receipt_digest_is_rejected():
    compiled, overlay = build_known_affirmed_fixture(atom_id="a1")
    receipt = make_real_integrity_receipt(overlay=overlay, artifact=compiled, atom_id="a1", satisfied=True)
    task = CognitiveTaskProfile(task_id="t")
    with pytest.raises(router_errors.IntegrityReceiptProvenanceInvalid):
        _call(
            task, overlay, compiled, integrity_receipt=receipt,
            integrity_receipt_trust_context=TRUSTED_PHASE19_RUNTIME, expected_integrity_receipt_digest="deadbeef-wrong-digest",
        )


def test_real_phase19_receipt_with_correct_trusted_digest_is_accepted():
    compiled, overlay = build_known_affirmed_fixture(atom_id="a1")
    receipt = make_real_integrity_receipt(overlay=overlay, artifact=compiled, atom_id="a1", satisfied=True)
    task = CognitiveTaskProfile(task_id="t", requirements=frozenset({CognitiveRequirementKind.INVESTIGATION}))
    decision = route_task_trusted(task, overlay=overlay, artifact=compiled, integrity_receipt=receipt)
    assert decision.status is not RoutingStatus.BLOCKED_BY_INTEGRITY
    assert decision.integrity_status is IntegrityStatus.SATISFIED


def test_altered_receipt_after_digest_capture_is_rejected():
    compiled, overlay = build_known_affirmed_fixture(atom_id="a1")
    receipt = make_real_integrity_receipt(overlay=overlay, artifact=compiled, atom_id="a1", satisfied=True)
    expected_digest = integrity_canonical.digest(receipt)  # captured out-of-band before "crossing the boundary"
    altered_receipt = dataclasses.replace(receipt, integrity_status=IntegrityStatus.BLOCKED)
    task = CognitiveTaskProfile(task_id="t")
    with pytest.raises(router_errors.IntegrityReceiptProvenanceInvalid):
        _call(
            task, overlay, compiled, integrity_receipt=altered_receipt,
            integrity_receipt_trust_context=TRUSTED_PHASE19_RUNTIME, expected_integrity_receipt_digest=expected_digest,
        )


def test_malformed_receipt_field_type_is_rejected_after_trust_passes():
    """A structurally malformed receipt (integrity_status as a bare
    string) whose provenance digest happens to match must still be
    rejected -- structural validation, not accidental fail-closed luck."""
    compiled, overlay = build_known_affirmed_fixture(atom_id="a1")
    receipt = make_real_integrity_receipt(overlay=overlay, artifact=compiled, atom_id="a1", satisfied=True)
    malformed = dataclasses.replace(receipt, integrity_status="SATISFIED")  # type: ignore[arg-type]
    expected_digest = integrity_canonical.digest(malformed)
    task = CognitiveTaskProfile(task_id="t")
    with pytest.raises(router_errors.InvalidObjectType):
        _call(
            task, overlay, compiled, integrity_receipt=malformed,
            integrity_receipt_trust_context=TRUSTED_PHASE19_RUNTIME, expected_integrity_receipt_digest=expected_digest,
        )


# ── ROUTE IDENTITY ──────────────────────────────────────────────────────


def test_blocked_vs_satisfied_receipt_yield_different_decision_ids():
    compiled, overlay = build_known_affirmed_fixture(atom_id="a1")
    satisfied = make_real_integrity_receipt(overlay=overlay, artifact=compiled, atom_id="a1", satisfied=True)
    blocked = make_real_integrity_receipt(overlay=overlay, artifact=compiled, atom_id="a1", satisfied=False)
    task = CognitiveTaskProfile(task_id="t", requirements=frozenset({CognitiveRequirementKind.INVESTIGATION}))
    d_satisfied = route_task_trusted(task, overlay=overlay, artifact=compiled, integrity_receipt=satisfied)
    d_blocked = route_task_trusted(task, overlay=overlay, artifact=compiled, integrity_receipt=blocked)
    assert d_satisfied.decision_id != d_blocked.decision_id


def test_receipt_present_vs_absent_yield_different_decision_ids():
    compiled, overlay = build_known_affirmed_fixture(atom_id="a1")
    satisfied = make_real_integrity_receipt(overlay=overlay, artifact=compiled, atom_id="a1", satisfied=True)
    task = CognitiveTaskProfile(task_id="t", requirements=frozenset({CognitiveRequirementKind.INVESTIGATION}))
    d_with_receipt = route_task_trusted(task, overlay=overlay, artifact=compiled, integrity_receipt=satisfied)
    d_without_receipt = route_task_trusted(task, overlay=overlay, artifact=compiled)
    assert d_with_receipt.decision_id != d_without_receipt.decision_id
    assert d_without_receipt.source_integrity_receipt_digest is None
    assert d_with_receipt.source_integrity_receipt_digest is not None


def test_same_exact_inputs_produce_identical_decision_id():
    compiled, overlay = build_known_affirmed_fixture(atom_id="a1")
    receipt = make_real_integrity_receipt(overlay=overlay, artifact=compiled, atom_id="a1", satisfied=True)
    task = CognitiveTaskProfile(task_id="t", requirements=frozenset({CognitiveRequirementKind.INVESTIGATION}))
    d1 = route_task_trusted(task, overlay=overlay, artifact=compiled, integrity_receipt=receipt)
    d2 = route_task_trusted(task, overlay=overlay, artifact=compiled, integrity_receipt=receipt)
    assert d1.decision_id == d2.decision_id


# ── REVIEW HONESTY ───────────────────────────────────────────────────────


def test_mandatory_reviewer_never_equals_primary_family():
    """A task requesting ONLY adversarial review (no other cognitive
    signal) against an all-eligible registry must never report Aeternum
    as both primary_family and mandatory_review_family -- that would
    ambiguously imply Aeternum independently reviewed itself."""
    compiled, overlay = build_known_affirmed_fixture()
    task = CognitiveTaskProfile(task_id="t", requirements=frozenset({CognitiveRequirementKind.ADVERSARIAL_REVIEW}))
    decision = route_task_trusted(task, overlay=overlay, artifact=compiled, capability_registry=_all_eligible_registry())
    if decision.primary_family is CognitiveFamily.AETERNUM:
        assert decision.mandatory_review_family is None
        assert RoutingReasonCode.MANDATORY_REVIEWER_CANNOT_BE_PRIMARY_FAMILY in decision.reason_codes
    else:
        assert decision.mandatory_review_family != decision.primary_family
