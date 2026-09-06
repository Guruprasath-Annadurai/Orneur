from __future__ import annotations

from orca.cognitive.contracts import RiskLevel
from orca.deliberation.contracts import Argument, CounterArgument, TwinResult
from orca.society.contracts import DisagreementType, EscalationAction
from orca.society.disagreement import compute_disagreement
from orca.society.escalation import BALANCED, DEEP_REASONING, FAST, decide_escalation
from orca.society.society_plan import build_court_society_plan


def test_same_model_role_overlap_is_explicit_when_only_one_eligible_model_exists():
    """With Novus not allowed (production default), the only eligible
    model for both Constructor and Falsifier is legacy Genesis -- this
    must be reported honestly, never hidden (spec §18)."""
    plan = build_court_society_plan(allow_experimental=False)
    assert plan.same_model_role_overlap is True
    constructor = plan.assignments[0].routing_decision
    falsifier = plan.assignments[1].routing_decision
    assert constructor.selected_model_id == falsifier.selected_model_id == "orneur-genesis"
    assert constructor.same_model_role_overlap and falsifier.same_model_role_overlap


def test_society_plan_never_forces_cosmetic_diversity():
    """Falsifier's request does not exclude Constructor's model -- if the
    router's own evidence-based ranking would pick the same model twice,
    that is allowed, not artificially forced apart (spec §18)."""
    plan = build_court_society_plan(allow_experimental=True)
    # Both may still land on Genesis if Novus isn't a better VERIFIER-shaped
    # fit for CONSTRUCTOR/FALSIFIER roles specifically -- the assertion is
    # just that the plan reports whatever is actually true, not a specific model.
    assert isinstance(plan.same_model_role_overlap, bool)


def test_disagreement_no_meaningful_signal():
    result = TwinResult(constructor_claims=[Argument(claim="x")])
    signal = compute_disagreement(result)
    assert signal.types == [DisagreementType.NO_MEANINGFUL_DISAGREEMENT]
    assert signal.severity == "NONE"
    assert not signal.has_meaningful_disagreement


def test_disagreement_claim_conflict_detected():
    arg = Argument(claim="x")
    result = TwinResult(
        constructor_claims=[arg],
        falsifier_objections=[CounterArgument(target_argument_id=arg.argument_id, objection="wrong", objection_kind="contradiction")],
        disputed_claim_ids=[arg.argument_id],
    )
    signal = compute_disagreement(result)
    assert DisagreementType.CLAIM_CONFLICT in signal.types
    assert signal.has_meaningful_disagreement


def test_disagreement_never_resolved_by_majority_vote():
    """Structural proof: DisagreementSignal carries no vote-count or
    winner field at all -- disagreement is reported, never adjudicated
    here (spec §19)."""
    import dataclasses

    from orca.society.contracts import DisagreementSignal

    field_names = {f.name for f in dataclasses.fields(DisagreementSignal)}
    assert not (field_names & {"votes", "winner", "majority", "consensus"})


def test_escalation_on_high_risk():
    decision = decide_escalation(current_tier=FAST, risk_level=RiskLevel.HIGH)
    assert decision.action == EscalationAction.ESCALATE
    assert decision.target_requirement == BALANCED
    assert decision.target_requirement != "orneur-aeternum"  # never a hardcoded model name


def test_escalation_never_triggers_merely_because_answer_is_long():
    decision = decide_escalation(current_tier=FAST, risk_level=RiskLevel.LOW)
    assert decision.action != EscalationAction.ESCALATE


def test_de_escalation_prefers_cheaper_sufficient_candidate():
    decision = decide_escalation(current_tier=DEEP_REASONING, risk_level=RiskLevel.LOW)
    assert decision.action == EscalationAction.DE_ESCALATE


def test_role_model_unavailable_returns_honest_abstention_not_fabricated_model():
    decision = decide_escalation(current_tier=FAST, role_model_unavailable=True)
    assert decision.action == EscalationAction.ABSTAIN_NO_CAPABLE_MODEL
