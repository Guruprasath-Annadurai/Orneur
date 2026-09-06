"""
RiskCounsel (Phase 6 spec §18). Considers consequence -- never
authorizes anything. Returns a recommendation the Arbiter weighs; it has
no power to accept/reject/execute on its own.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from orca.cognitive.contracts import RiskLevel


@dataclass
class RiskOpinion:
    risk_level: RiskLevel = RiskLevel.LOW
    recommendation: str = ""          # "proceed" | "more_verification" | "simulation" | "human_approval" | "abstain"
    reasons: list[str] = field(default_factory=list)


def assess_risk_opinion(risk_level: RiskLevel, evidence_report, unresolved_questions: list[str]) -> RiskOpinion:
    reasons: list[str] = []

    if risk_level == RiskLevel.CRITICAL:
        reasons.append("CRITICAL risk -- irreversible/high-consequence action implied")
        if evidence_report.direct_contradiction_count > 0 or evidence_report.claims_missing_evidence:
            return RiskOpinion(risk_level=risk_level, recommendation="human_approval", reasons=reasons + ["unresolved contradiction or missing evidence at CRITICAL risk"])
        return RiskOpinion(risk_level=risk_level, recommendation="human_approval", reasons=reasons + ["CRITICAL risk always recommends human approval, regardless of evidence quality"])

    if risk_level == RiskLevel.HIGH:
        reasons.append("HIGH risk")
        if evidence_report.direct_contradiction_count > 0:
            return RiskOpinion(risk_level=risk_level, recommendation="more_verification", reasons=reasons + ["unresolved direct contradiction"])
        if evidence_report.claims_missing_evidence:
            return RiskOpinion(risk_level=risk_level, recommendation="more_verification", reasons=reasons + ["claims without evidence at HIGH risk"])
        if unresolved_questions:
            return RiskOpinion(risk_level=risk_level, recommendation="simulation", reasons=reasons + ["unresolved questions remain -- counterfactual/simulation may help"])
        return RiskOpinion(risk_level=risk_level, recommendation="proceed", reasons=reasons + ["evidence supports proceeding, no unresolved contradiction"])

    if evidence_report.direct_contradiction_count > 0:
        return RiskOpinion(risk_level=risk_level, recommendation="more_verification", reasons=["unresolved direct contradiction even at lower risk"])

    return RiskOpinion(risk_level=risk_level, recommendation="proceed", reasons=["risk is LOW/MODERATE and evidence has no unresolved contradiction"])
