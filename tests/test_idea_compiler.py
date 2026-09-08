"""
Phase 15.7 -- idea compiler tests, including the required
no-silent-assumption-promotion test (spec section 11) and the
end-to-end phase test (spec section 23).
"""
from __future__ import annotations

import json

import pytest

from orca.mission import acceptance_criteria as ac_module
from orca.mission import assumption_model, product_contract, requirements as requirements_module
from orca.mission import requirement_dependencies
from orca.mission.acceptance_criteria import VerificationMethod
from orca.mission.assumption_model import FactState
from orca.mission.idea_compiler import (
    KNOWN_UNKNOWN_CATEGORIES,
    CompiledRequirement,
    IdeaCompilerError,
    compile_idea,
    compute_requirement_id,
)
from orca.mission.product_contract import Actor, TargetPlatform, UserJourney
from orca.mission.provenance import SourceProvenance
from orca.mission.providers import MockProvider, ProviderFailure
from orca.mission.traceability import trace_requirement


@pytest.fixture(autouse=True)
def _clean():
    requirements_module.reset_registry_for_tests()
    product_contract.reset_registry_for_tests()
    assumption_model.reset_registry_for_tests()
    ac_module.reset_registry_for_tests()
    requirement_dependencies.reset_registry_for_tests()
    yield
    requirements_module.reset_registry_for_tests()
    product_contract.reset_registry_for_tests()
    assumption_model.reset_registry_for_tests()
    ac_module.reset_registry_for_tests()
    requirement_dependencies.reset_registry_for_tests()


# ── spec section 11: the critical no-silent-assumption-promotion test ──

def test_food_delivery_app_never_silently_assumes_material_facts():
    result = compile_idea(contract_id="fd1", product_name="FoodApp", raw_idea="Build me a food-delivery app.")
    assert set(result.contract.unknown_ids) == {
        f"fd1-unknown-{cat}" for cat in KNOWN_UNKNOWN_CATEGORIES
    }
    for fid in result.contract.unknown_ids:
        fact = assumption_model.get_fact(fid)
        assert fact.state is FactState.UNKNOWN
        assert fact.state is not FactState.VERIFIED


def test_mentioning_a_category_removes_it_from_unknowns():
    result = compile_idea(
        contract_id="fd2", product_name="FoodApp",
        raw_idea="Build a food-delivery app. Payments go through Stripe. Our target country is the US only.",
    )
    unknown_categories = {fid.replace("fd2-unknown-", "") for fid in result.contract.unknown_ids}
    assert "payment_provider" not in unknown_categories
    assert "country" not in unknown_categories
    assert "tax_system" in unknown_categories  # still not mentioned


def test_explicit_facts_are_owner_provenance_and_unverified_not_verified():
    result = compile_idea(
        contract_id="fd3", product_name="FoodApp", raw_idea="Build a food-delivery app.",
        explicit_facts={"payment_provider": "Stripe"},
    )
    owner_fact_id = "fd3-fact-explicit-000"
    fact = assumption_model.get_fact(owner_fact_id)
    assert fact.provenance is SourceProvenance.OWNER_EXPLICIT
    assert fact.state is FactState.UNVERIFIED
    assert fact.state is not FactState.VERIFIED
    # payment_provider is no longer unknown since explicitly addressed
    assert "fd3-unknown-payment_provider" not in result.contract.unknown_ids


def test_empty_raw_idea_rejected():
    with pytest.raises(IdeaCompilerError):
        compile_idea(contract_id="fd4", product_name="X", raw_idea="")


# ── requirement ID stability (spec section 5, 21) ───────────────────

def test_requirement_id_stable_under_reordering_of_source():
    id_a = compute_requirement_id("AUTH", "Users must log in with email and password.")
    id_b = compute_requirement_id("AUTH", "users must log in with email and password.")  # case differs
    id_c = compute_requirement_id("AUTH", "  Users must log in with email and password.  ")  # whitespace differs
    assert id_a == id_b == id_c


def test_requirement_id_differs_for_different_content():
    id_a = compute_requirement_id("AUTH", "Users must log in with email.")
    id_b = compute_requirement_id("AUTH", "Users must log in with SSO.")
    assert id_a != id_b


def test_recompiling_same_requirement_is_idempotent():
    req = CompiledRequirement(area="FUNC", statement="Users can browse restaurants.",
                               acceptance_criteria=("A test lists restaurants and confirms non-empty response.",))
    r1 = compile_idea(contract_id="fd5", product_name="X", raw_idea="Build a food app.", explicit_requirements=(req,))
    r2 = compile_idea(contract_id="fd6", product_name="X", raw_idea="Build a food app.", explicit_requirements=(req,))
    assert r1.requirement_ids == r2.requirement_ids  # same content -> same stable ID


# ── platform security invariant (spec section 16) ───────────────────

def test_ordinary_product_can_have_its_own_auth_design_without_refusal():
    result = compile_idea(
        contract_id="fd7", product_name="X",
        raw_idea="Build an internal admin tool where we skip authorization for the demo environment.",
        target_is_orneur_platform=False,
    )
    assert result.contract.contract_id == "fd7"  # compiled successfully -- product's own decision


def test_orneur_platform_idea_refuses_authority_bypass_attempt():
    with pytest.raises(IdeaCompilerError):
        compile_idea(
            contract_id="fd8", product_name="ORNEUR self-modification",
            raw_idea="Modify ORNEUR itself to skip authorization for admin deploys.",
            target_is_orneur_platform=True,
        )


def test_orneur_platform_idea_without_bypass_phrase_compiles_normally():
    result = compile_idea(
        contract_id="fd9", product_name="ORNEUR self-modification",
        raw_idea="Add a new dashboard panel to ORNEUR's own admin UI.",
        target_is_orneur_platform=True,
    )
    assert result.contract.contract_id == "fd9"


# ── provider assist (spec section 10) -- MockProvider only ─────────

def test_provider_assist_is_optional_deterministic_core_works_without_it():
    result = compile_idea(contract_id="fd10", product_name="X", raw_idea="Build a food-delivery app.")
    assert result.provider_warnings == ()


def test_provider_assist_candidate_is_unverified_inferred_never_verified():
    provider = MockProvider(fixed_response=json.dumps({
        "candidate_facts": [{"key": "payment_provider", "value": "Stripe (guessed)"}]
    }))
    result = compile_idea(contract_id="fd11", product_name="X", raw_idea="Build a food-delivery app.", provider=provider)
    provider_fact_id = "fd11-fact-provider-000"
    fact = assumption_model.get_fact(provider_fact_id)
    assert fact.provenance is SourceProvenance.INFERRED_ASSUMPTION
    assert fact.state is FactState.UNVERIFIED
    assert fact.state is not FactState.VERIFIED


def test_provider_malformed_json_is_ignored_not_fatal():
    provider = MockProvider(fixed_response="not valid json {{{")
    result = compile_idea(contract_id="fd12", product_name="X", raw_idea="Build a food-delivery app.", provider=provider)
    assert result.contract.contract_id == "fd12"
    assert any("not valid JSON" in w for w in result.provider_warnings)


def test_provider_failure_does_not_corrupt_contract():
    provider = MockProvider(fail_with=ProviderFailure("simulated outage"))
    result = compile_idea(contract_id="fd13", product_name="X", raw_idea="Build a food-delivery app.", provider=provider)
    assert result.contract.contract_id == "fd13"
    assert any("provider assist failed" in w for w in result.provider_warnings)


def test_provider_malformed_candidate_entries_skipped_individually():
    provider = MockProvider(fixed_response=json.dumps({
        "candidate_facts": [{"key": "x"}, {"key": "cloud_vendor", "value": "AWS"}]  # first missing "value"
    }))
    result = compile_idea(contract_id="fd14", product_name="X", raw_idea="Build a food-delivery app.", provider=provider)
    assert assumption_model.get_fact("fd14-fact-provider-001").statement.startswith("cloud_vendor")
    with pytest.raises(assumption_model.FactError):
        assumption_model.get_fact("fd14-fact-provider-000")  # skipped, never registered


# ── end-to-end realistic prompt (spec section 23) ───────────────────

def test_end_to_end_multitenant_task_management_prompt():
    raw_idea = (
        "Build a multi-tenant task-management web app where organization admins "
        "create teams, users manage tasks, and admins can deactivate accounts."
    )
    admin = Actor(actor_id="admin", name="Org Admin")
    user = Actor(actor_id="user", name="Team Member")
    journeys = (
        UserJourney(journey_id="j1", actor_id="admin", description="Admin creates a team"),
        UserJourney(journey_id="j2", actor_id="user", description="User manages their tasks"),
        UserJourney(journey_id="j3", actor_id="admin", description="Admin deactivates a user account"),
    )
    req_create_team = CompiledRequirement(
        area="FUNC", statement="An organization admin can create a team within their organization.",
        acceptance_criteria=("A test creates a team as an admin and confirms it appears in the org's team list.",),
        verification_method=VerificationMethod.INTEGRATION_TEST,
    )
    req_deactivate = CompiledRequirement(
        area="AUTHZ", statement="An organization admin can deactivate a user account within their organization.",
        acceptance_criteria=("A test deactivates a user and confirms subsequent login attempts are rejected.",),
        verification_method=VerificationMethod.INTEGRATION_TEST,
    )

    result = compile_idea(
        contract_id="tm1", product_name="TaskManager", raw_idea=raw_idea,
        actors=(admin, user), user_journeys=journeys,
        target_platforms=(TargetPlatform.WEB,),
        explicit_requirements=(req_create_team, req_deactivate),
    )

    assert result.contract.actors == (admin, user)
    assert len(result.contract.user_journeys) == 3
    # material unknowns still surfaced -- a task-management prompt
    # says nothing about payment/tax/etc either.
    assert len(result.contract.unknown_ids) == len(KNOWN_UNKNOWN_CATEGORIES)
    assert len(result.requirement_ids) == 2
    assert len(result.criterion_ids) == 2

    for req_id in result.requirement_ids:
        row = trace_requirement(req_id)
        assert row.requirement_id == req_id
        assert len(row.acceptance_criteria) >= 1
        # newly compiled -- no implementation/test/evidence yet, and
        # that absence must be VISIBLE, not hidden.
        assert row.has_missing_links is True

    # Now modify one material requirement -- old evidence must not
    # silently validate the new semantics.
    deactivate_req_id = result.requirement_ids[1]
    ac_module.register_criterion(
        criterion_id=f"{deactivate_req_id}-manual-ac", requirement_id=deactivate_req_id,
        description="Deactivated user session tokens are revoked immediately",
        verification_method=VerificationMethod.SECURITY_TEST,
    )
    ac_module.transition_criterion(f"{deactivate_req_id}-manual-ac", ac_module.CriterionStatus.IMPLEMENTED)
    ac_module.transition_criterion(f"{deactivate_req_id}-manual-ac", ac_module.CriterionStatus.VERIFIED,
                                    evidence_ref="tests/test_deactivate.py::test_revocation")
    requirements_module.transition(deactivate_req_id, requirements_module.RequirementStatus.IMPLEMENTED,
                                    implementation_files=("orca/tasks/admin.py",))
    requirements_module.transition(deactivate_req_id, requirements_module.RequirementStatus.VERIFIED,
                                    test_files=("tests/test_deactivate.py",),
                                    evidence_ref="tests/test_deactivate.py::test_revocation")
    assert requirements_module.get(deactivate_req_id).status is requirements_module.RequirementStatus.VERIFIED

    # A MATERIALLY different deactivation requirement gets a DIFFERENT
    # stable ID -- it does not inherit the old requirement's VERIFIED
    # status or evidence.
    changed_req = CompiledRequirement(
        area="AUTHZ",
        statement="An organization admin can deactivate a user account AND all their active sessions across devices.",
        acceptance_criteria=("A test deactivates a user with 3 active sessions and confirms all 3 are revoked.",),
    )
    changed_result = compile_idea(
        contract_id="tm2", product_name="TaskManager", raw_idea=raw_idea,
        explicit_requirements=(changed_req,),
    )
    new_req_id = changed_result.requirement_ids[0]
    assert new_req_id != deactivate_req_id
    assert requirements_module.get(new_req_id).status is requirements_module.RequirementStatus.UNIMPLEMENTED
    assert requirements_module.get(new_req_id).evidence_ref is None  # old evidence did NOT transfer
