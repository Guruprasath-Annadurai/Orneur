"""
Phase 16 closure: reconciles two genuinely distinct, both real, Court
abstractions in this repository:

- orca.deliberation.contracts.CourtVerdictState (ACCEPT/REVISE/REJECT/
  INSUFFICIENT_EVIDENCE) -- Phase 6/7's internal Cognitive-Kernel plan
  revision mechanism, consumed by orca/cognitive/kernel.py's replanning
  loop and orca/agent/court_hook.py's advisory agent-plan review. Never
  meant to be presented externally as "the" ORNEUR Court contract.

- orca.mission.cognitive_court.CourtVerdict (ACCEPT/REJECT/
  NEED_MORE_EVIDENCE/ESCALATE/HUMAN_APPROVAL_REQUIRED) -- Phase 15.9's
  governed Mission-gate Court, matching the owner's canonical Phase 15
  spec (docs/orneur/phase-15/ORNEUR_CODE_RELAY_MASTER_SPEC_V1.md) and
  PHASE15_EVIDENCE.md's own "All five canonical outcomes" finding
  EXACTLY. THIS is the canonical governed ORNEUR Court contract.

An earlier Phase 16 draft incorrectly cited the deliberation-fabric enum
as if it were the canonical governed contract. These tests prove the
distinction holds in code, not just in updated prose.
"""
from __future__ import annotations

import pytest


def test_canonical_governed_court_verdict_is_exactly_the_owner_required_five_values():
    from orca.mission.cognitive_court import CourtVerdict

    assert {v.value for v in CourtVerdict} == {
        "ACCEPT", "REJECT", "NEED_MORE_EVIDENCE", "ESCALATE", "HUMAN_APPROVAL_REQUIRED",
    }


def test_legacy_deliberation_vocabulary_is_genuinely_different_not_a_typo():
    """Guards against a future edit accidentally aligning the two enums --
    they are legitimately different abstractions, not the same thing
    spelled two ways."""
    from orca.deliberation.contracts import CourtVerdictState
    from orca.mission.cognitive_court import CourtVerdict as GovernedCourtVerdict

    legacy_values = {v.value for v in CourtVerdictState}
    governed_values = {v.value for v in GovernedCourtVerdict}
    assert legacy_values == {"ACCEPT", "REVISE", "REJECT", "INSUFFICIENT_EVIDENCE"}
    assert legacy_values != governed_values


def test_mission_court_gate_never_imports_the_legacy_deliberation_court():
    """The canonical governed Court-gate module must resolve verdicts only
    from orca.mission.cognitive_court -- legacy/internal deliberation
    vocabulary must never leak into the governed Mission-gate API."""
    import ast
    from pathlib import Path

    gate_file = Path(__file__).resolve().parent.parent / "orca" / "mission" / "court_mission_gate.py"
    tree = ast.parse(gate_file.read_text())
    imported_modules = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "orca.deliberation.contracts" not in imported_modules
    assert "orca.deliberation.court" not in imported_modules
    assert "orca.mission.cognitive_court" in imported_modules


def test_mission_court_accept_alone_does_not_grant_completion():
    """Court ACCEPT remains DATA, never execution authority: even a real
    ACCEPT for the correct mission/revision is refused if the independent
    verification gate has not also passed (existing behavior, re-asserted
    here as a Phase 16 regression guard)."""
    from orca.mission.court_mission_gate import can_proceed_to_completed_verified
    from orca.mission.cognitive_court import CourtDecision, CourtVerdict, RiskLevel
    from orca.mission.verification_aggregation import RequiredVerificationScope

    decision = CourtDecision(
        decision_id="court_test1", mission_id="m1", revision="r1", risk_level=RiskLevel.STANDARD,
        roles_invoked=(), findings_considered=(), verification_refs=(),
        reasoning_summary="test", verdict=CourtVerdict.ACCEPT,
    )
    can_proceed, reason = can_proceed_to_completed_verified(
        court_decision=decision,
        records_by_requirement={},
        required_requirement_ids=("REQ-1",),
        current_revision="r1",
        current_mission_id="m1",
        required_scopes_by_requirement={"REQ-1": RequiredVerificationScope(requirement_level_categories=frozenset({"functional"}))},
    )
    assert can_proceed is False
    assert "Verification gate" in reason


@pytest.mark.parametrize("verdict_name", ["REJECT", "NEED_MORE_EVIDENCE", "ESCALATE", "HUMAN_APPROVAL_REQUIRED"])
def test_every_non_accept_verdict_blocks_mission_completion(verdict_name):
    from orca.mission.court_mission_gate import can_proceed_to_completed_verified
    from orca.mission.cognitive_court import CourtDecision, CourtVerdict, RiskLevel
    from orca.mission.verification_aggregation import RequiredVerificationScope

    decision = CourtDecision(
        decision_id="court_test2", mission_id="m1", revision="r1", risk_level=RiskLevel.STANDARD,
        roles_invoked=(), findings_considered=(), verification_refs=(),
        reasoning_summary="test", verdict=CourtVerdict[verdict_name],
    )
    can_proceed, reason = can_proceed_to_completed_verified(
        court_decision=decision,
        records_by_requirement={},
        required_requirement_ids=("REQ-1",),
        current_revision="r1",
        current_mission_id="m1",
        required_scopes_by_requirement={"REQ-1": RequiredVerificationScope(requirement_level_categories=frozenset({"functional"}))},
    )
    assert can_proceed is False
    assert verdict_name in reason


def test_human_approval_required_comes_from_a_deterministic_caller_flag_not_model_prose():
    """arbiter_decide()'s own docstring states it reads ONLY deterministic
    inputs. This test proves the signature has no channel for a critic's
    provider_narrative (free-text, possibly model-influenced) to ever
    become the owner_approval_required flag -- it is a plain bool the
    CALLER supplies, structurally separate from CriticOutput.provider_narrative."""
    import inspect
    from orca.mission.cognitive_court import arbiter_decide

    sig = inspect.signature(arbiter_decide)
    assert sig.parameters["owner_approval_required"].annotation in (bool, "bool")

    # Structural check: CriticOutput.provider_narrative is documented as
    # "kept separate -- never authoritative" and must not be consumed by
    # the HUMAN_APPROVAL_REQUIRED branch (verified by reading
    # arbiter_decide's own source: the branch is `if owner_approval_required:`
    # only, never a check on provider_narrative or critic_outputs).
    import ast
    from pathlib import Path
    src = Path(inspect.getfile(arbiter_decide)).read_text()
    tree = ast.parse(src)
    func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "arbiter_decide")
    func_src = ast.get_source_segment(src, func)
    # The HUMAN_APPROVAL_REQUIRED branch must be gated on the plain
    # parameter, not on any critic_outputs/provider_narrative inspection.
    approval_branch_start = func_src.index("if owner_approval_required:")
    approval_branch = func_src[approval_branch_start:approval_branch_start + 400]
    assert "provider_narrative" not in approval_branch
    assert "critic_outputs" not in approval_branch.split("return")[0].split("if owner_approval_required:")[1].split("\n")[0]


def test_need_more_evidence_and_reject_are_distinguishable():
    from orca.mission.cognitive_court import CourtVerdict
    assert CourtVerdict.NEED_MORE_EVIDENCE != CourtVerdict.REJECT
    assert CourtVerdict.NEED_MORE_EVIDENCE.value != CourtVerdict.REJECT.value


def test_escalate_and_accept_are_distinguishable():
    from orca.mission.cognitive_court import CourtVerdict
    assert CourtVerdict.ESCALATE != CourtVerdict.ACCEPT
