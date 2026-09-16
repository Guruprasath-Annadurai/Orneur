"""
Spec section 25, behavioral classes A-O: the routing outcomes a real
caller depends on. Every fixture here is a genuine Phase 17 artifact +
genuine Phase 18 assess_artifact() overlay, never a mock.
"""
from __future__ import annotations

import dataclasses

import pytest

from orneur.intelligence.epistemic import EpistemicState
from orneur.intelligence.integrity.enums import IntegrityStatus
from orneur.intelligence.router import (
    CognitiveFamily,
    CognitiveRequirementKind,
    CognitiveTaskProfile,
    IntelligenceCapabilityProfile,
    RoutingReasonCode,
    RoutingStatus,
    RuntimeAvailability,
    RuntimeLifecycleState,
    build_default_capability_registry,
    digest,
)
from tests.router.conftest import (
    build_disputed_fixture,
    build_known_affirmed_fixture,
    build_unknown_fixture,
    make_real_integrity_receipt,
    route_task_trusted,
)


def _genesis_eligible_registry():
    """A custom registry making Genesis eligible, for tests exercising
    behavioral classes that need a routing-eligible BUILDER_EXECUTOR --
    the honest default registry has only Novus eligible (see
    registry.py's module docstring)."""
    return tuple(
        dataclasses.replace(
            entry, lifecycle_state=RuntimeLifecycleState.EXPERIMENTAL, runtime_availability=RuntimeAvailability.AVAILABLE,
        )
        if entry.family is CognitiveFamily.GENESIS
        else entry
        for entry in build_default_capability_registry()
    )


def _all_eligible_registry():
    return tuple(
        dataclasses.replace(
            entry, lifecycle_state=RuntimeLifecycleState.EXPERIMENTAL, runtime_availability=RuntimeAvailability.AVAILABLE,
        )
        for entry in build_default_capability_registry()
    )


# A. Routine implementation work routes to Genesis when eligible.
def test_routine_implementation_routes_to_genesis_when_eligible():
    compiled, overlay = build_known_affirmed_fixture()
    task = CognitiveTaskProfile(task_id="t", requirements=frozenset({CognitiveRequirementKind.IMPLEMENTATION}))
    decision = route_task_trusted(task, overlay=overlay, artifact=compiled, capability_registry=_genesis_eligible_registry())
    assert decision.status is RoutingStatus.SELECTED
    assert decision.primary_family is CognitiveFamily.GENESIS


# B. Investigation preference over implementation-only: when a task is
# investigative-shaped and BOTH a builder and an investigator are
# independently eligible for that exact requirement set, the
# REASONER_INVESTIGATOR role wins by design -- Aeternum's own
# adversarial role is never picked as a plain investigative default.
def test_investigative_requirement_prefers_novus_role_priority():
    compiled, overlay = build_known_affirmed_fixture()
    registry = tuple(
        dataclasses.replace(
            entry,
            lifecycle_state=RuntimeLifecycleState.EXPERIMENTAL,
            runtime_availability=RuntimeAvailability.AVAILABLE,
            supported_requirements=entry.supported_requirements | {CognitiveRequirementKind.INVESTIGATION},
        )
        if entry.family is CognitiveFamily.GENESIS
        else entry
        for entry in build_default_capability_registry()
    )
    task = CognitiveTaskProfile(task_id="t", requirements=frozenset({CognitiveRequirementKind.INVESTIGATION}))
    decision = route_task_trusted(task, overlay=overlay, artifact=compiled, capability_registry=registry)
    genesis_eval = next(c for c in decision.candidate_evaluations if c.family is CognitiveFamily.GENESIS)
    assert genesis_eval.eligible is True  # both are genuinely eligible here
    assert decision.primary_family is CognitiveFamily.NOVUS


# A task requiring capabilities no single family covers together fails
# closed rather than guessing a partial match (single-owner-of-primary-
# role design: a RoutingDecision never implies two families split one
# task).
def test_disjoint_combined_requirements_with_no_single_covering_family_fails_closed():
    compiled, overlay = build_known_affirmed_fixture()
    task = CognitiveTaskProfile(
        task_id="t",
        requirements=frozenset({CognitiveRequirementKind.IMPLEMENTATION, CognitiveRequirementKind.INVESTIGATION}),
    )
    decision = route_task_trusted(task, overlay=overlay, artifact=compiled, capability_registry=_genesis_eligible_registry())
    assert decision.status is RoutingStatus.NO_ELIGIBLE_ROUTE
    assert decision.primary_family is None


# C. UNKNOWN material premise adds an implicit INVESTIGATION requirement
# and is preserved (Cognitive Conservation) in the decision.
def test_unknown_material_atom_forces_investigation_and_is_conserved():
    compiled, overlay = build_unknown_fixture(atom_id="a1")
    task = CognitiveTaskProfile(task_id="t", material_epistemic_atom_ids=("a1",))
    decision = route_task_trusted(task, overlay=overlay, artifact=compiled)
    assert decision.status is RoutingStatus.INVESTIGATION_REQUIRED
    assert decision.primary_family is CognitiveFamily.NOVUS
    assert RoutingReasonCode.UNKNOWN_PREMISE_REQUIRES_INVESTIGATION in decision.reason_codes
    assert len(decision.material_epistemic_factors) == 1
    assert decision.material_epistemic_factors[0].epistemic_state is EpistemicState.UNKNOWN


# D. DISPUTED material premise surfaces a review-shaped requirement,
# never silently dropped.
def test_disputed_material_atom_surfaces_contradiction_resolution():
    compiled, overlay = build_disputed_fixture(atom_id="a1")
    task = CognitiveTaskProfile(task_id="t", material_epistemic_atom_ids=("a1",))
    decision = route_task_trusted(task, overlay=overlay, artifact=compiled)
    assert RoutingReasonCode.DISPUTED_PREMISE_REQUIRES_REVIEW in decision.reason_codes
    assert decision.material_epistemic_factors[0].epistemic_state is EpistemicState.DISPUTED


# E. Adversarial review requirement and its unavailability being
# surfaced honestly (default registry has no eligible Aeternum).
def test_adversarial_review_requirement_with_unavailable_reviewer_is_honest():
    compiled, overlay = build_known_affirmed_fixture()
    task = CognitiveTaskProfile(task_id="t", requirements=frozenset({CognitiveRequirementKind.ADVERSARIAL_REVIEW}))
    decision = route_task_trusted(task, overlay=overlay, artifact=compiled)
    assert decision.status is RoutingStatus.REVIEW_REQUIRED
    assert decision.mandatory_review_family is None
    assert RoutingReasonCode.ADVERSARIAL_REVIEWER_UNAVAILABLE in decision.reason_codes
    assert RoutingReasonCode.ADVERSARIAL_REVIEW_REQUIRED in decision.reason_codes


def test_adversarial_review_requirement_with_available_reviewer_is_granted():
    compiled, overlay = build_known_affirmed_fixture()
    task = CognitiveTaskProfile(
        task_id="t",
        requirements=frozenset({CognitiveRequirementKind.INVESTIGATION, CognitiveRequirementKind.ADVERSARIAL_REVIEW}),
    )
    decision = route_task_trusted(task, overlay=overlay, artifact=compiled, capability_registry=_all_eligible_registry())
    assert decision.status is RoutingStatus.REVIEW_REQUIRED
    assert decision.mandatory_review_family is CognitiveFamily.AETERNUM
    assert RoutingReasonCode.ADVERSARIAL_REVIEWER_UNAVAILABLE not in decision.reason_codes


# F. Capability/lifecycle mismatch produces an explicit, typed rejection
# reason per-candidate -- never a silent drop.
def test_capability_mismatch_rejection_reasons_are_recorded_per_candidate():
    compiled, overlay = build_known_affirmed_fixture()
    task = CognitiveTaskProfile(task_id="t", requirements=frozenset({CognitiveRequirementKind.IMPLEMENTATION}))
    decision = route_task_trusted(task, overlay=overlay, artifact=compiled)  # default registry: Genesis unavailable
    genesis_eval = next(c for c in decision.candidate_evaluations if c.family is CognitiveFamily.GENESIS)
    assert genesis_eval.eligible is False
    assert RoutingReasonCode.RUNTIME_UNAVAILABLE in genesis_eval.rejection_reasons
    assert RoutingReasonCode.LIFECYCLE_INELIGIBLE in genesis_eval.rejection_reasons


# G. Self-elevation attempts: metadata/preferred_family cannot grant
# eligibility a trusted registry entry does not independently confer.
def test_preferred_family_cannot_self_elevate_ineligible_candidate():
    compiled, overlay = build_known_affirmed_fixture()
    task = CognitiveTaskProfile(
        task_id="t", requirements=frozenset({CognitiveRequirementKind.INVESTIGATION}), preferred_family=CognitiveFamily.AETERNUM,
    )
    decision = route_task_trusted(task, overlay=overlay, artifact=compiled)
    assert decision.primary_family is not CognitiveFamily.AETERNUM
    assert RoutingReasonCode.PREFERENCE_NOT_ELIGIBLE in decision.reason_codes


def test_task_metadata_field_named_like_authority_grants_nothing():
    compiled, overlay = build_known_affirmed_fixture()
    task = CognitiveTaskProfile(
        task_id="t",
        requirements=frozenset({CognitiveRequirementKind.INVESTIGATION}),
        metadata={"trusted": True, "approved": True, "execution_grant": "full", "lifecycle_state": "PRODUCTION"},
    )
    decision = route_task_trusted(task, overlay=overlay, artifact=compiled)
    # Only Novus is eligible per the trusted registry regardless of
    # what the untrusted metadata claims.
    assert decision.primary_family is CognitiveFamily.NOVUS


# H. No eligible candidate -> fail-closed, typed NO_ELIGIBLE_ROUTE.
def test_no_eligible_candidate_fails_closed():
    compiled, overlay = build_known_affirmed_fixture()
    empty_registry = ()
    task = CognitiveTaskProfile(task_id="t", requirements=frozenset({CognitiveRequirementKind.IMPLEMENTATION}))
    decision = route_task_trusted(task, overlay=overlay, artifact=compiled, capability_registry=empty_registry)
    assert decision.status is RoutingStatus.NO_ELIGIBLE_ROUTE
    assert decision.primary_family is None
    assert RoutingReasonCode.NO_CANDIDATE_ELIGIBLE in decision.reason_codes


# A task establishing no cognitive requirement at all (no explicit
# requirement, no material-atom-derived requirement) fails closed
# rather than picking an arbitrary available family.
def test_empty_effective_requirements_fails_closed_as_no_cognitive_requirement():
    compiled, overlay = build_known_affirmed_fixture()
    task = CognitiveTaskProfile(task_id="t")
    decision = route_task_trusted(task, overlay=overlay, artifact=compiled)
    assert decision.status is RoutingStatus.NO_ELIGIBLE_ROUTE
    assert decision.primary_family is None
    assert decision.reason_codes == (RoutingReasonCode.NO_COGNITIVE_REQUIREMENT,)
    assert decision.candidate_evaluations == ()


# I. Determinism: identical input -> byte-identical canonical decision.
def test_same_input_produces_byte_identical_canonical_decision():
    compiled, overlay = build_known_affirmed_fixture()
    task = CognitiveTaskProfile(task_id="t", requirements=frozenset({CognitiveRequirementKind.INVESTIGATION}))
    d1 = route_task_trusted(task, overlay=overlay, artifact=compiled)
    d2 = route_task_trusted(task, overlay=overlay, artifact=compiled)
    assert digest(d1) == digest(d2)
    assert d1.decision_id == d2.decision_id


# J. Candidate-order independence: registry entries in any order yield
# the same decision.
def test_registry_entry_order_does_not_affect_decision():
    compiled, overlay = build_known_affirmed_fixture()
    task = CognitiveTaskProfile(task_id="t", requirements=frozenset({CognitiveRequirementKind.INVESTIGATION}))
    forward = build_default_capability_registry()
    reversed_registry = tuple(reversed(forward))
    d1 = route_task_trusted(task, overlay=overlay, artifact=compiled, capability_registry=forward)
    d2 = route_task_trusted(task, overlay=overlay, artifact=compiled, capability_registry=reversed_registry)
    assert digest(d1) == digest(d2)


# K. Integrity-blocked input is rejected from routing outright. Uses a
# GENUINE Phase-19 assess_integrity() output (real REQUIRES_REVISION,
# not a fabricated BLOCKED dataclass) -- any non-SATISFIED status
# blocks routing.
def test_integrity_blocked_input_never_routes_as_clean():
    compiled, overlay = build_known_affirmed_fixture(atom_id="a1")
    receipt = make_real_integrity_receipt(overlay=overlay, artifact=compiled, atom_id="a1", satisfied=False)
    assert receipt.integrity_status is not IntegrityStatus.SATISFIED
    task = CognitiveTaskProfile(task_id="t", requirements=frozenset({CognitiveRequirementKind.IMPLEMENTATION}))
    decision = route_task_trusted(task, overlay=overlay, artifact=compiled, integrity_receipt=receipt, capability_registry=_genesis_eligible_registry())
    assert decision.status is RoutingStatus.BLOCKED_BY_INTEGRITY
    assert decision.primary_family is None
    assert decision.candidate_evaluations == ()
    assert decision.reason_codes == (RoutingReasonCode.INTEGRITY_BLOCKED,)
    assert decision.source_integrity_receipt_digest is not None


def test_satisfied_integrity_receipt_permits_normal_routing():
    compiled, overlay = build_known_affirmed_fixture(atom_id="a1")
    receipt = make_real_integrity_receipt(overlay=overlay, artifact=compiled, atom_id="a1", satisfied=True)
    assert receipt.integrity_status is IntegrityStatus.SATISFIED
    task = CognitiveTaskProfile(task_id="t", requirements=frozenset({CognitiveRequirementKind.INVESTIGATION}))
    decision = route_task_trusted(task, overlay=overlay, artifact=compiled, integrity_receipt=receipt)
    assert decision.status is not RoutingStatus.BLOCKED_BY_INTEGRITY
    assert decision.primary_family is CognitiveFamily.NOVUS
    assert decision.integrity_status is IntegrityStatus.SATISFIED
    assert decision.source_integrity_receipt_digest is not None


# L. Forged overlay content cannot gain routing influence -- exercised
# directly against evaluator.route_task() (not the trusted wrapper,
# which computes its expected digest from the SAME correct overlay).
def test_forged_overlay_content_cannot_influence_routing():
    from orneur.intelligence.integrity import errors as integrity_errors
    from orneur.intelligence.router.evaluator import route_task
    from tests.router.conftest import TRUSTED_PHASE18_RUNTIME
    from orneur.intelligence.epistemic import canonical as epistemic_canonical

    compiled, overlay = build_known_affirmed_fixture(atom_id="a1")
    legitimate_expected_digest = epistemic_canonical.digest(overlay)

    forged_state = EpistemicState.KNOWN if overlay.assessments[0].state != EpistemicState.KNOWN else EpistemicState.UNCERTAIN
    forged_assessment = dataclasses.replace(overlay.assessments[0], state=forged_state)
    forged_overlay = dataclasses.replace(overlay, assessments=(forged_assessment,))

    task = CognitiveTaskProfile(task_id="t", material_epistemic_atom_ids=("a1",))
    with pytest.raises(integrity_errors.OverlayProvenanceInvalid):
        route_task(
            task, overlay=forged_overlay, artifact=compiled,
            overlay_trust_context=TRUSTED_PHASE18_RUNTIME,
            expected_overlay_digest=legitimate_expected_digest,
        )


# M. Routing is not authority: a RoutingDecision alone never causes any
# side effect -- it is verified elsewhere (test_no_authority.py) via
# static analysis; here we confirm it is inert plain data.
def test_routing_decision_is_frozen_plain_data():
    compiled, overlay = build_known_affirmed_fixture()
    decision = route_task_trusted(CognitiveTaskProfile(task_id="t"), overlay=overlay, artifact=compiled)
    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.status = RoutingStatus.SELECTED  # type: ignore[misc]


# N. Unknown material atom reference is rejected, never silently
# dropped or silently treated as UNKNOWN state.
def test_unreferenced_material_atom_id_is_rejected():
    from orneur.intelligence.router import errors as router_errors

    compiled, overlay = build_known_affirmed_fixture(atom_id="a1")
    task = CognitiveTaskProfile(task_id="t", material_epistemic_atom_ids=("does-not-exist",))
    with pytest.raises(router_errors.UnknownEpistemicAtomReference):
        route_task_trusted(task, overlay=overlay, artifact=compiled)


# O. A caller-supplied capability registry is validated, not trusted
# blindly -- a duplicate family entry is rejected.
def test_duplicate_registry_family_is_rejected():
    from orneur.intelligence.router import errors as router_errors

    compiled, overlay = build_known_affirmed_fixture()
    dup_registry = build_default_capability_registry()[:2] + (build_default_capability_registry()[0],)
    task = CognitiveTaskProfile(task_id="t")
    with pytest.raises(router_errors.DuplicateRegistryFamily):
        route_task_trusted(task, overlay=overlay, artifact=compiled, capability_registry=dup_registry)
