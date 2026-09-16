"""
Closure: normalize_policy() raw TypeError hole. Reproduced defect:
`frozenset(declared)` was called BEFORE validating each member's type,
so an unhashable member (a dict or list) raised a raw
`TypeError: unhashable type` that escaped Phase 19's public boundary.
Fixed: every member's type is validated by iterating the raw `declared`
container FIRST; frozenset() is only ever called on an
already-type-validated collection.
"""
from __future__ import annotations

import pytest

from orneur.intelligence.epistemic.enums import EpistemicState
from orneur.intelligence.integrity import errors
from orneur.intelligence.integrity.contracts import IntegrityPolicy, IntegrityProposal
from orneur.intelligence.integrity.enums import PresentationTreatment
from tests.integrity.conftest import assess_integrity_trusted, build_known_affirmed_fixture


def _assess_with_policy(policy):
    artifact, overlay = build_known_affirmed_fixture()
    return assess_integrity_trusted(IntegrityProposal(proposal_id="p1", assertions=()), overlay=overlay, artifact=artifact, policy=policy)


@pytest.mark.parametrize("unhashable_member", [{}, [], {"x": 1}, {1, 2}])
def test_unhashable_policy_member_reproduces_as_typed_error_not_raw_typeerror(unhashable_member):
    policy = IntegrityPolicy(stricter_permitted_treatments={EpistemicState.KNOWN: [unhashable_member]})
    try:
        _assess_with_policy(policy)
        assert False, "expected an exception"
    except errors.InvalidIntegrityPolicy:
        pass
    except TypeError as exc:
        pytest.fail(f"a raw TypeError escaped instead of InvalidIntegrityPolicy: {exc}")


@pytest.mark.parametrize("bad_member", [None, "ABSTAIN", 1, True, object()])
def test_hashable_but_wrong_type_policy_member_rejected(bad_member):
    policy = IntegrityPolicy(stricter_permitted_treatments={EpistemicState.KNOWN: [bad_member]})
    with pytest.raises(errors.InvalidIntegrityPolicy):
        _assess_with_policy(policy)


def test_epistemic_state_member_used_as_treatment_rejected():
    """A category-confused value that IS a real enum, but the WRONG
    enum (EpistemicState instead of PresentationTreatment)."""
    policy = IntegrityPolicy(stricter_permitted_treatments={EpistemicState.KNOWN: [EpistemicState.KNOWN]})
    with pytest.raises(errors.InvalidIntegrityPolicy):
        _assess_with_policy(policy)


def test_mixed_valid_and_invalid_members_still_rejected():
    """One genuine PresentationTreatment plus one unhashable member in
    the same collection -- the whole declaration fails closed, no
    partial acceptance."""
    policy = IntegrityPolicy(stricter_permitted_treatments={EpistemicState.KNOWN: [PresentationTreatment.ABSTAIN, {}]})
    with pytest.raises(errors.InvalidIntegrityPolicy):
        _assess_with_policy(policy)


def test_all_genuine_members_still_accepted_after_the_fix():
    """Regression guard: the fix must not have broken the legitimate
    path -- a real, valid frozenset of PresentationTreatment members
    still normalizes correctly."""
    policy = IntegrityPolicy(stricter_permitted_treatments={EpistemicState.KNOWN: {PresentationTreatment.ABSTAIN}})
    receipt = _assess_with_policy(policy)
    assert receipt is not None


def test_validation_order_checks_member_types_before_frozenset_conversion():
    """Direct unit-level proof of the fix's ordering: floor.normalize_policy
    iterates the raw container (which may hold unhashable members)
    BEFORE ever calling frozenset() on it."""
    from orneur.intelligence.integrity.contracts import IntegrityPolicy as Policy
    from orneur.intelligence.integrity.floor import normalize_policy

    policy = Policy(stricter_permitted_treatments={EpistemicState.KNOWN: [{}]})
    with pytest.raises(errors.InvalidIntegrityPolicy):
        normalize_policy(policy)
