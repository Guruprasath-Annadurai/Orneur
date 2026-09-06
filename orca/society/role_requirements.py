"""
Role requirement declarations (Phase 7 spec §6). Each role declares what it
needs, never which model to use -- the router (orca/society/router.py)
resolves an actual eligible model against these requirements plus live
lifecycle/entitlement/health state.
"""
from __future__ import annotations

from orca.society.contracts import CognitiveRole, RoleRequirement

# min_lifecycle_rank uses orca.society.lifecycle.lifecycle_rank's ordering:
# REJECTED/RETIRED < EXPERIMENTAL < CANDIDATE < EVALUATING < APPROVED < TRAINED < PRODUCTION
# A role requiring rank 0 accepts EXPERIMENTAL (still hard-filtered by
# allow_experimental at the request level, per spec §38/§47).
ROLE_REQUIREMENTS: dict[CognitiveRole, RoleRequirement] = {
    CognitiveRole.FAST_RESPONDER: RoleRequirement(
        role=CognitiveRole.FAST_RESPONDER, latency_sensitive=True, min_context_tokens=1024, cost_sensitive=True,
    ),
    CognitiveRole.INTENT_COMPILER: RoleRequirement(
        role=CognitiveRole.INTENT_COMPILER, latency_sensitive=True, requires_structured_output=True, min_context_tokens=1024,
    ),
    CognitiveRole.RETRIEVAL_PLANNER: RoleRequirement(
        role=CognitiveRole.RETRIEVAL_PLANNER, requires_structured_output=True, min_context_tokens=2048,
    ),
    CognitiveRole.QUERY_REWRITER: RoleRequirement(
        role=CognitiveRole.QUERY_REWRITER, latency_sensitive=True, min_context_tokens=1024,
    ),
    CognitiveRole.CLAIM_EXTRACTOR: RoleRequirement(
        role=CognitiveRole.CLAIM_EXTRACTOR, requires_structured_output=True, evidence_sensitive=True, min_context_tokens=2048,
    ),
    CognitiveRole.MEMORY_SELECTOR: RoleRequirement(
        role=CognitiveRole.MEMORY_SELECTOR, requires_structured_output=True, min_context_tokens=2048,
    ),
    CognitiveRole.CONSTRUCTOR: RoleRequirement(
        role=CognitiveRole.CONSTRUCTOR, requires_structured_output=True, requires_reasoning=True,
        evidence_sensitive=True, min_context_tokens=2048,
    ),
    CognitiveRole.FALSIFIER: RoleRequirement(
        role=CognitiveRole.FALSIFIER, requires_structured_output=True, requires_reasoning=True,
        requires_verification=True, evidence_sensitive=True, risk_sensitive=True, min_context_tokens=2048,
    ),
    CognitiveRole.VERIFIER: RoleRequirement(
        role=CognitiveRole.VERIFIER, requires_verification=True, evidence_sensitive=True, min_context_tokens=2048,
    ),
    CognitiveRole.CODER: RoleRequirement(
        role=CognitiveRole.CODER, requires_structured_output=True, requires_reasoning=True, min_context_tokens=4096,
    ),
    CognitiveRole.TOOL_REASONER: RoleRequirement(
        role=CognitiveRole.TOOL_REASONER, requires_tool_calling=True, requires_reasoning=True, min_context_tokens=2048,
    ),
    CognitiveRole.CAUSAL_REASONER: RoleRequirement(
        role=CognitiveRole.CAUSAL_REASONER, requires_reasoning=True, evidence_sensitive=True, min_context_tokens=2048,
    ),
    CognitiveRole.COUNTERFACTUAL_REASONER: RoleRequirement(
        role=CognitiveRole.COUNTERFACTUAL_REASONER, requires_reasoning=True, min_context_tokens=2048,
    ),
    CognitiveRole.SUMMARIZER: RoleRequirement(
        role=CognitiveRole.SUMMARIZER, latency_sensitive=True, min_context_tokens=2048,
    ),
    CognitiveRole.ARBITRATION_SUPPORT: RoleRequirement(
        role=CognitiveRole.ARBITRATION_SUPPORT, requires_reasoning=True, risk_sensitive=True, min_context_tokens=2048,
    ),
}


def requirement_for(role: CognitiveRole) -> RoleRequirement:
    return ROLE_REQUIREMENTS[role]
