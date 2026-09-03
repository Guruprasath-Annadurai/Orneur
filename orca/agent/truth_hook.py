"""
Explicit Truth Fabric runtime integration (Phase 8.1 spec §12-14). NOT
forced on every action -- only actions/planning assumptions the planner
(or a caller) has explicitly marked `AgentAction.requires_truth_check=True`
ever trigger a Truth Fabric call. Epistemic verification (Truth Fabric) is
kept explicitly distinct from OPERATIONAL verification (a tool read-back/
status check -- see `AgentRuntime._to_observation`, unchanged, spec §14).
"""
from __future__ import annotations


async def truth_check_sufficient(objective: str, *, doc_store=None, budget=None) -> bool:
    """
    Runs `TruthFabric.assess_evidence()` (the SAME Phase 4/4.1 evidence
    authority every other subsystem uses -- no second retrieval/
    verification stack) and returns whether the evidence found is
    SUFFICIENT. Callers wire this as `AgentRuntime`'s `truth_checker` for
    actions/assumptions marked `requires_truth_check=True` -- if this
    returns False, the runtime does NOT guess-and-execute (spec §13); it
    treats the action as failed (eligible for the SAME bounded local
    replan mechanism already used for tool failures).
    """
    from orca.cognitive.contracts import ComplexityAssessment, ComplexityLevel, IntentCategory, IntentPlan
    from orca.truth.contracts import EvidenceState, FreshnessLevel, TruthRequest
    from orca.truth.truth_fabric import TruthFabric

    fabric = TruthFabric()
    request = TruthRequest(objective=objective, freshness_requirement=FreshnessLevel.STATIC)
    intent = IntentPlan(primary_intent=IntentCategory.FACTUAL)
    complexity_assessment = ComplexityAssessment(level=ComplexityLevel.LOW, score=0.1)
    result = await fabric.assess_evidence(request, intent, complexity_assessment, doc_store=doc_store, budget=budget)
    return result.evidence_state == EvidenceState.SUFFICIENT
