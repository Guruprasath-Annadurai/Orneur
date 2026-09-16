"""
Phase 20 ROLE-DRIVEN closure (spec section 17): primary selection must
be a function of cognitive ROLE, never the literal family name. Every
scenario here swaps roles across families in a synthetic trusted
registry to prove selection genuinely follows role, not identity.
"""
from __future__ import annotations

import dataclasses

from orneur.intelligence.router import (
    CognitiveFamily,
    CognitiveRequirementKind,
    CognitiveRole,
    CognitiveTaskProfile,
    RoutingReasonCode,
    RoutingStatus,
    RuntimeAvailability,
    RuntimeLifecycleState,
    build_default_capability_registry,
)
from tests.router.conftest import build_known_affirmed_fixture, route_task_trusted


def _swap_roles_registry(*, genesis_role, novus_role, requirement, both_eligible=True):
    return tuple(
        dataclasses.replace(
            e, role=genesis_role,
            lifecycle_state=RuntimeLifecycleState.EXPERIMENTAL if both_eligible else e.lifecycle_state,
            runtime_availability=RuntimeAvailability.AVAILABLE if both_eligible else e.runtime_availability,
            supported_requirements=frozenset({requirement}),
        )
        if e.family is CognitiveFamily.GENESIS
        else dataclasses.replace(
            e, role=novus_role,
            lifecycle_state=RuntimeLifecycleState.EXPERIMENTAL, runtime_availability=RuntimeAvailability.AVAILABLE,
            supported_requirements=frozenset({requirement}),
        )
        if e.family is CognitiveFamily.NOVUS
        else e
        for e in build_default_capability_registry()
    )


# A. INVESTIGATION with roles swapped: Genesis holds REASONER_INVESTIGATOR.
def test_investigation_swapped_roles_selects_genesis_by_role():
    compiled, overlay = build_known_affirmed_fixture()
    registry = _swap_roles_registry(
        genesis_role=CognitiveRole.REASONER_INVESTIGATOR, novus_role=CognitiveRole.BUILDER_EXECUTOR,
        requirement=CognitiveRequirementKind.INVESTIGATION,
    )
    task = CognitiveTaskProfile(task_id="t", requirements=frozenset({CognitiveRequirementKind.INVESTIGATION}))
    decision = route_task_trusted(task, overlay=overlay, artifact=compiled, capability_registry=registry)
    assert decision.primary_family is CognitiveFamily.GENESIS
    assert decision.status is RoutingStatus.INVESTIGATION_REQUIRED


# B. IMPLEMENTATION with roles swapped: Novus holds BUILDER_EXECUTOR.
def test_implementation_swapped_roles_selects_novus_by_role():
    compiled, overlay = build_known_affirmed_fixture()
    registry = _swap_roles_registry(
        genesis_role=CognitiveRole.REASONER_INVESTIGATOR, novus_role=CognitiveRole.BUILDER_EXECUTOR,
        requirement=CognitiveRequirementKind.IMPLEMENTATION,
    )
    task = CognitiveTaskProfile(task_id="t", requirements=frozenset({CognitiveRequirementKind.IMPLEMENTATION}))
    decision = route_task_trusted(task, overlay=overlay, artifact=compiled, capability_registry=registry)
    assert decision.primary_family is CognitiveFamily.NOVUS
    assert decision.status is RoutingStatus.SELECTED


# C. Tie: two eligible candidates with the same correct role -> stable
# documented family-value tie-break (alphabetical: AETERNUM < GENESIS < NOVUS).
def test_tie_between_same_role_candidates_uses_family_value_tie_break():
    compiled, overlay = build_known_affirmed_fixture()
    registry = tuple(
        dataclasses.replace(
            e, role=CognitiveRole.REASONER_INVESTIGATOR,
            lifecycle_state=RuntimeLifecycleState.EXPERIMENTAL, runtime_availability=RuntimeAvailability.AVAILABLE,
            supported_requirements=frozenset({CognitiveRequirementKind.INVESTIGATION}),
        )
        if e.family in (CognitiveFamily.GENESIS, CognitiveFamily.NOVUS)
        else e
        for e in build_default_capability_registry()
    )
    task = CognitiveTaskProfile(task_id="t", requirements=frozenset({CognitiveRequirementKind.INVESTIGATION}))
    decision = route_task_trusted(task, overlay=overlay, artifact=compiled, capability_registry=registry)
    assert decision.primary_family is CognitiveFamily.GENESIS  # "GENESIS" < "NOVUS" alphabetically


# D. Preferred family capability-eligible but WRONG role -> preference
# cannot bypass role adequacy.
def test_preferred_family_with_wrong_role_cannot_bypass_role_adequacy():
    compiled, overlay = build_known_affirmed_fixture()
    registry = _swap_roles_registry(
        genesis_role=CognitiveRole.BUILDER_EXECUTOR, novus_role=CognitiveRole.REASONER_INVESTIGATOR,
        requirement=CognitiveRequirementKind.INVESTIGATION, both_eligible=False,
    )
    # Genesis here has BUILDER_EXECUTOR role but is NOT lifecycle-eligible
    # (left at NOT_TRAINED/UNAVAILABLE) -- irrelevant to this test's point,
    # which is that even an ELIGIBLE wrong-role candidate can't be preferred.
    # Make Genesis eligible but with the WRONG role for this INVESTIGATION task.
    registry = tuple(
        dataclasses.replace(
            e, role=CognitiveRole.BUILDER_EXECUTOR,
            lifecycle_state=RuntimeLifecycleState.EXPERIMENTAL, runtime_availability=RuntimeAvailability.AVAILABLE,
            supported_requirements=frozenset({CognitiveRequirementKind.INVESTIGATION}),
        )
        if e.family is CognitiveFamily.GENESIS
        else e
        for e in build_default_capability_registry()
    )
    task = CognitiveTaskProfile(
        task_id="t", requirements=frozenset({CognitiveRequirementKind.INVESTIGATION}), preferred_family=CognitiveFamily.GENESIS,
    )
    decision = route_task_trusted(task, overlay=overlay, artifact=compiled, capability_registry=registry)
    # Genesis is capability-eligible (supports INVESTIGATION, lifecycle
    # AVAILABLE) but holds BUILDER_EXECUTOR, not REASONER_INVESTIGATOR --
    # the preference must be ignored, and Novus (the genuine
    # REASONER_INVESTIGATOR) selected instead.
    assert decision.primary_family is CognitiveFamily.NOVUS
    assert RoutingReasonCode.PREFERENCE_NOT_ELIGIBLE in decision.reason_codes


# E. Reviewer selection follows ROLE, not the literal family name
# "AETERNUM" -- a non-Aeternum family holding CRITIC_ARBITER_DISCOVERER
# and supporting the review requirement is selected as reviewer.
def test_reviewer_selection_follows_role_not_family_name():
    compiled, overlay = build_known_affirmed_fixture()
    registry = tuple(
        dataclasses.replace(
            e, role=CognitiveRole.CRITIC_ARBITER_DISCOVERER,
            lifecycle_state=RuntimeLifecycleState.EXPERIMENTAL, runtime_availability=RuntimeAvailability.AVAILABLE,
            supported_requirements=frozenset({CognitiveRequirementKind.ADVERSARIAL_REVIEW}),
        )
        if e.family is CognitiveFamily.GENESIS  # Genesis, not Aeternum, holds the critic role here
        else e
        for e in build_default_capability_registry()
    )
    task = CognitiveTaskProfile(
        task_id="t", requirements=frozenset({CognitiveRequirementKind.INVESTIGATION, CognitiveRequirementKind.ADVERSARIAL_REVIEW}),
    )
    decision = route_task_trusted(task, overlay=overlay, artifact=compiled, capability_registry=registry)
    assert decision.primary_family is CognitiveFamily.NOVUS  # REASONER_INVESTIGATOR, unaffected by the role swap
    assert decision.mandatory_review_family is CognitiveFamily.GENESIS  # the role-holder, not "AETERNUM"


# F. Current default registry: behavior remains consistent with actual
# current model availability (Novus only, Genesis/Aeternum unavailable).
def test_default_registry_behavior_remains_truthful():
    compiled, overlay = build_known_affirmed_fixture()
    investigative = route_task_trusted(
        CognitiveTaskProfile(task_id="t1", requirements=frozenset({CognitiveRequirementKind.INVESTIGATION})),
        overlay=overlay, artifact=compiled,
    )
    assert investigative.primary_family is CognitiveFamily.NOVUS

    implementation = route_task_trusted(
        CognitiveTaskProfile(task_id="t2", requirements=frozenset({CognitiveRequirementKind.IMPLEMENTATION})),
        overlay=overlay, artifact=compiled,
    )
    assert implementation.status is RoutingStatus.NO_ELIGIBLE_ROUTE
    assert implementation.primary_family is None


# No candidate has the required role even though other capability-
# eligible candidates exist -> explicit ROLE_ADEQUACY_NOT_SATISFIED,
# never a silent role mismatch treated as a match.
def test_role_adequacy_not_satisfied_when_no_eligible_candidate_has_required_role():
    compiled, overlay = build_known_affirmed_fixture()
    # Novus is capability-eligible for IMPLEMENTATION (broadened here)
    # but still holds its real REASONER_INVESTIGATOR role -- no
    # candidate anywhere has BUILDER_EXECUTOR.
    registry = tuple(
        dataclasses.replace(e, supported_requirements=e.supported_requirements | {CognitiveRequirementKind.IMPLEMENTATION})
        if e.family is CognitiveFamily.NOVUS
        else e
        for e in build_default_capability_registry()
    )
    task = CognitiveTaskProfile(task_id="t", requirements=frozenset({CognitiveRequirementKind.IMPLEMENTATION}))
    decision = route_task_trusted(task, overlay=overlay, artifact=compiled, capability_registry=registry)
    assert decision.status is RoutingStatus.NO_ELIGIBLE_ROUTE
    assert decision.primary_family is None
    assert RoutingReasonCode.ROLE_ADEQUACY_NOT_SATISFIED in decision.reason_codes
