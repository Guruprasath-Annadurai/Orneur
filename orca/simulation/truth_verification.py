"""
Real Truth Fabric integration for simulation assumptions (Phase 11.1
spec §18-24). Converts Phase 11's conceptual "assumptions may request
Truth Fabric verification" into an actual runtime hook -- reuses
`orca.truth.truth_fabric.TruthFabric.assess_evidence()` directly (the
SAME Phase 4/4.1 evidence authority every other subsystem uses, exactly
`orca.agent.truth_hook.truth_check_sufficient()`'s own pattern), never a
second, parallel truth/verification stack.
"""
from __future__ import annotations

from dataclasses import dataclass

from orca.simulation.contracts import Assumption

_TRUTH_SIGNED_STATES = {"VERIFIED", "CONTESTED", "STALE", "UNVERIFIED"}


@dataclass
class AssumptionVerificationContext:
    """Deterministic trigger inputs (spec §19) -- never "send every
    assumption to Truth Fabric." Each flag independently justifies a
    real verification call."""
    freshness_sensitive: bool = False
    externally_factual: bool = False
    high_impact: bool = False
    audit_grade: bool = False
    contradicted: bool = False
    stale_or_unknown: bool = False


def requires_truth_verification(ctx: AssumptionVerificationContext) -> bool:
    return any([ctx.freshness_sensitive, ctx.externally_factual, ctx.high_impact, ctx.audit_grade, ctx.contradicted, ctx.stale_or_unknown])


def _evidence_level_for(ctx: AssumptionVerificationContext):
    from orca.cognitive.contracts import EvidenceLevel
    if ctx.audit_grade:
        return EvidenceLevel.AUDIT_GRADE
    if ctx.contradicted or ctx.high_impact:
        return EvidenceLevel.STRICT
    return EvidenceLevel.SUPPORTED


def _freshness_for(ctx: AssumptionVerificationContext):
    from orca.cognitive.contracts import FreshnessLevel
    if ctx.freshness_sensitive:
        return FreshnessLevel.CURRENT
    return FreshnessLevel.STATIC


def build_truth_request(assumption: Assumption, *, simulation_id: str, ctx: AssumptionVerificationContext):
    """
    Bounded Truth Fabric request (spec §20) -- preserves simulation_id/
    assumption_id via `context_refs` (references only, never raw
    payload/secret content), claim via `objective` (the assumption's own
    `description`, never anything else), and the freshness/evidence
    level the trigger context implies.
    """
    from orca.truth.contracts import TruthRequest
    return TruthRequest(
        objective=assumption.description,
        evidence_requirement=_evidence_level_for(ctx),
        freshness_requirement=_freshness_for(ctx),
        context_refs=[f"simulation:{simulation_id}", f"assumption:{assumption.assumption_id}"],
    )


def map_evidence_state_to_verification(evidence_state) -> str:
    """
    spec §21: use EXISTING Truth semantics, never an invented parallel
    one. `EvidenceState` (orca.truth.contracts) -> assumption
    verification state:

        SUFFICIENT  -> VERIFIED
        CONFLICTED  -> CONTESTED
        STALE       -> STALE
        INSUFFICIENT (and anything else) -> UNVERIFIED
    """
    value = evidence_state.value if hasattr(evidence_state, "value") else str(evidence_state)
    return {"SUFFICIENT": "VERIFIED", "CONFLICTED": "CONTESTED", "STALE": "STALE"}.get(value, "UNVERIFIED")


async def verify_assumption(
    assumption: Assumption, *, simulation_id: str, ctx: AssumptionVerificationContext, doc_store=None, budget=None,
) -> Assumption:
    """
    Real runtime call -- `TruthFabric.assess_evidence()`, no fabricated
    result. Truth retrieval/model calls consume the SAME `budget`
    (`CognitiveBudget`, unchanged dimensions) any other Truth Fabric
    caller uses (spec §23) -- simulation gets no separate free Truth
    budget; the caller must pass a real `budget` for this to be
    accounted at all, exactly like `orca.agent.truth_hook`'s own
    pattern.

    Returns a NEW `Assumption` (never mutates the input) with
    `verification_state` set from the real result -- a model/user/tool
    claiming "assumption verified" has zero effect here (spec §45): only
    this function's own call into `TruthFabric` can produce `VERIFIED`.
    """
    from orca.cognitive.contracts import ComplexityAssessment, ComplexityLevel, IntentCategory, IntentPlan
    from orca.truth.truth_fabric import TruthFabric

    if not requires_truth_verification(ctx):
        return assumption

    request = build_truth_request(assumption, simulation_id=simulation_id, ctx=ctx)
    intent = IntentPlan(primary_intent=IntentCategory.FACTUAL)
    complexity = ComplexityAssessment(level=ComplexityLevel.LOW, score=0.1)

    fabric = TruthFabric()
    result = await fabric.assess_evidence(request, intent, complexity, doc_store=doc_store, budget=budget)
    new_state = map_evidence_state_to_verification(result.evidence_state)

    return Assumption(
        assumption_id=assumption.assumption_id, description=assumption.description,
        source="truth_fabric_verification", verification_state=new_state, impact_if_false=assumption.impact_if_false,
    )
