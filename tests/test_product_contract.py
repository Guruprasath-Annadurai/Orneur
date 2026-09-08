"""Phase 15.7 -- ProductContract test matrix (spec section 19)."""
from __future__ import annotations

import pytest

from orca.mission.product_contract import (
    Actor,
    ContractError,
    LaunchTarget,
    ProductContract,
    TargetPlatform,
    UserJourney,
    all_contracts,
    get_contract,
    register_contract,
    reset_registry_for_tests,
    revise_contract,
)


@pytest.fixture(autouse=True)
def _clean():
    reset_registry_for_tests()
    yield
    reset_registry_for_tests()


def _minimal(contract_id="c1", **overrides):
    defaults = dict(
        contract_id=contract_id, version=1, product_name="X", product_purpose="Do a thing",
        source_input="raw idea text", created_at="2026-01-01T00:00:00Z",
    )
    defaults.update(overrides)
    return ProductContract(**defaults)


def test_valid_minimal_contract():
    c = register_contract(_minimal())
    assert get_contract("c1") is c


def test_valid_rich_contract():
    alice = Actor(actor_id="a1", name="Admin")
    bob = Actor(actor_id="a2", name="User")
    journey = UserJourney(journey_id="j1", actor_id="a2", description="User places an order")
    c = _minimal(
        actors=(alice, bob), user_journeys=(journey,),
        target_platforms=(TargetPlatform.WEB, TargetPlatform.IOS),
        launch_target=LaunchTarget.ENGINEERING_READY,
        out_of_scope=("payment processing v1",),
        acceptance_targets=("core browsing flow works",),
    )
    register_contract(c)
    assert get_contract("c1").actors == (alice, bob)


def test_missing_purpose_rejected():
    with pytest.raises(ContractError):
        _minimal(product_purpose="")


def test_missing_source_input_rejected():
    with pytest.raises(ContractError):
        _minimal(source_input="")


def test_duplicate_actor_ids_rejected():
    a1 = Actor(actor_id="a1", name="Admin")
    a2 = Actor(actor_id="a1", name="AnotherAdmin")
    with pytest.raises(ContractError):
        _minimal(actors=(a1, a2))


def test_journey_referencing_unknown_actor_rejected():
    journey = UserJourney(journey_id="j1", actor_id="ghost", description="does something")
    with pytest.raises(ContractError):
        _minimal(user_journeys=(journey,))


def test_unknown_fields_remain_none_not_invented():
    c = _minimal()
    assert c.authentication_needs is None
    assert c.permission_model is None
    assert c.launch_target is None
    assert c.data_classes == ()


def test_out_of_scope_preserved_and_distinguished_from_acceptance():
    with pytest.raises(ContractError):
        _minimal(out_of_scope=("feature x",), acceptance_targets=("feature x",))
    c = _minimal(out_of_scope=("feature x",), acceptance_targets=("feature y",))
    assert "feature x" in c.out_of_scope
    assert "feature x" not in c.acceptance_targets


def test_target_platform_validation_uses_controlled_enum():
    c = _minimal(target_platforms=(TargetPlatform.WEB,))
    assert c.target_platforms == (TargetPlatform.WEB,)


def test_launch_target_cannot_be_published_no_such_value():
    assert not hasattr(LaunchTarget, "PUBLISHED")


def test_duplicate_contract_id_rejected():
    register_contract(_minimal())
    with pytest.raises(ContractError):
        register_contract(_minimal())


def test_contract_version_semantics_via_revision():
    register_contract(_minimal())
    revised = revise_contract("c1", new_contract_id="c1-v2", change_reason="scope changed", product_purpose="Do a bigger thing")
    assert revised.version == 2
    assert revised.supersedes == "c1"
    old = get_contract("c1")
    assert old.superseded_by == "c1-v2"
    assert old.product_purpose == "Do a thing"  # old semantics NOT rewritten
    assert revised.product_purpose == "Do a bigger thing"


def test_cannot_revise_already_superseded_contract():
    register_contract(_minimal())
    revise_contract("c1", new_contract_id="c1-v2", change_reason="r1")
    with pytest.raises(ContractError):
        revise_contract("c1", new_contract_id="c1-v3", change_reason="r2")


def test_revise_requires_nonempty_change_reason():
    register_contract(_minimal())
    with pytest.raises(ContractError):
        revise_contract("c1", new_contract_id="c1-v2", change_reason="")


def test_invalid_evidence_state_combination_at_higher_layer_not_this_module():
    # ProductContract itself carries no evidence/state field directly
    # (that lives in Fact/AcceptanceCriterion) -- this test documents
    # the boundary rather than asserting something ProductContract
    # doesn't model.
    c = _minimal()
    assert not hasattr(c, "evidence_ref")
