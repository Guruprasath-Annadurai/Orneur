"""
Phase 6: Cognitive Court wired into CognitiveKernel's Truth-Fabric-
answered path (spec §40-43). Simple requests bypass Court entirely
(spec §42's fast-path requirement) -- proven directly on the
ReasoningCompiler's own output, not just asserted.
"""
from __future__ import annotations

from orca.cognitive.contracts import ComplexityLevel, EvidenceLevel, RiskLevel
from orca.deliberation.compiler import compile_reasoning_plan


def test_direct_contradiction_triggers_court_but_temporal_reconciliation_does_not():
    """Regression: a real bug found and fixed while wiring this up --
    ANY non-empty contradictions list (including TEMPORALLY_RECONCILABLE/
    SCOPE_DIFFERENCE, which Truth Fabric itself already classifies as
    "not actually a standing conflict") was triggering Court, causing a
    previously-reliable STRICT request to newly abstain. Only
    DIRECT_CONTRADICTION should count as a real evidence-conflict signal."""
    from orca.truth.contracts import Contradiction, ContradictionRelationship

    class _FakeTruthResult:
        contradictions = [Contradiction(claim_a_id="e1", claim_b_id="e2", relationship=ContradictionRelationship.TEMPORALLY_RECONCILABLE)]

    plan = compile_reasoning_plan("Where is the Eiffel Tower?", ComplexityLevel.LOW, RiskLevel.LOW, EvidenceLevel.STRICT, truth_result=_FakeTruthResult())
    assert not plan.requires_court

    class _FakeTruthResultDirect:
        contradictions = [Contradiction(claim_a_id="e1", claim_b_id="e2", relationship=ContradictionRelationship.DIRECT_CONTRADICTION)]

    plan2 = compile_reasoning_plan("Where is the Eiffel Tower?", ComplexityLevel.LOW, RiskLevel.LOW, EvidenceLevel.STRICT, truth_result=_FakeTruthResultDirect())
    assert plan2.requires_court


def test_simple_conversational_request_never_requires_court():
    plan = compile_reasoning_plan("Thanks, that's helpful!", ComplexityLevel.LOW, RiskLevel.LOW, EvidenceLevel.NONE)
    assert not plan.requires_court
    assert plan.mode.value == "DIRECT"
