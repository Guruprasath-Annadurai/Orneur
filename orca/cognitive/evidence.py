"""
Evidence Requirement -- how strongly an answer must be grounded (Phase 3
spec §12). Deliberately does NOT implement the Truth Fabric: this only
classifies the required grounding strength; actually obtaining/verifying
evidence is future work (RETRIEVE/VERIFY operations are PLANNED, not
SUPPORTED_NOW -- see planner.py).
"""
from __future__ import annotations

from orca.cognitive.contracts import (
    EvidenceLevel,
    EvidenceRequirement,
    IntentCategory,
    IntentPlan,
    RiskAssessment,
    RiskLevel,
)

_CREATIVE_INTENTS = {IntentCategory.CONVERSATIONAL, IntentCategory.UNKNOWN}
_STRICT_INTENTS = {IntentCategory.RESEARCH}


def assess_evidence_requirement(intent: IntentPlan, risk: RiskAssessment) -> EvidenceRequirement:
    """
    Ordering, most specific first:
      - CRITICAL/HIGH risk -> AUDIT_GRADE / STRICT (a destructive or
        security-sensitive request must be the most tightly grounded,
        regardless of intent category)
      - citation_requirement or RESEARCH intent -> STRICT
      - purely conversational/unknown intent -> NONE
      - everything else (the common case: a normal factual/reasoning
        answer) -> SUPPORTED
    """
    if risk.level == RiskLevel.CRITICAL:
        return EvidenceRequirement(level=EvidenceLevel.AUDIT_GRADE, reasons=["risk=CRITICAL requires audit-grade grounding"])
    if risk.level == RiskLevel.HIGH:
        return EvidenceRequirement(level=EvidenceLevel.STRICT, reasons=["risk=HIGH requires strict grounding"])

    if intent.primary_intent in _STRICT_INTENTS or intent.citation_requirement:
        return EvidenceRequirement(level=EvidenceLevel.STRICT, reasons=["research/citation-bearing intent requires strict grounding"])

    if intent.primary_intent in _CREATIVE_INTENTS and not intent.citation_requirement:
        return EvidenceRequirement(level=EvidenceLevel.NONE, reasons=["conversational/unclassified intent with no citation requirement"])

    return EvidenceRequirement(level=EvidenceLevel.SUPPORTED, reasons=["default: a normal factual/reasoning answer should be groundable"])
