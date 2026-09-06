"""
Arbiter (Phase 6 spec §19-20). Produces the final structured
CourtVerdict. Deterministic, rule-based aggregation over the other
roles' STRUCTURED outputs -- never a model vote, never "ask a model for
the verdict and trust it" (the same mistake orca/variants/ultra.py's
single 0-100 grade call makes, audited in
docs/orneur/phase-6/CURRENT_REASONING_ARCHITECTURE.md). Resolution
considers evidence, contradictions, source quality, and falsification
outcome -- never a vote count (spec §20).
"""
from __future__ import annotations

from orca.deliberation.contracts import CourtVerdict, CourtVerdictState
from orca.deliberation.evidence_clerk import EvidenceReport
from orca.deliberation.risk_counsel import RiskOpinion
from orca.deliberation.twin import TwinResult


def arbitrate(twin_result: TwinResult, evidence_report: EvidenceReport, risk_opinion: RiskOpinion, audit_grade: bool = False) -> CourtVerdict:
    reasons: list[str] = []

    # 1. No claims at all -> nothing to accept.
    if not twin_result.constructor_claims:
        return CourtVerdict(
            verdict=CourtVerdictState.INSUFFICIENT_EVIDENCE, decision_reasons=["Constructor produced no claims"],
            confidence=0.0, epistemic_state="UNVERIFIED",
        )

    # 2. Critical unresolved contradiction blocks ACCEPT for high-risk/
    # audit-grade decisions (spec §39) -- checked BEFORE anything else,
    # regardless of how strong the surviving claims otherwise look.
    if evidence_report.direct_contradiction_count > 0 and (audit_grade or risk_opinion.risk_level.value in ("HIGH", "CRITICAL")):
        reasons.append(f"{evidence_report.direct_contradiction_count} unresolved direct contradiction(s) -- blocks ACCEPT at this risk/evidence level")
        return CourtVerdict(
            verdict=CourtVerdictState.INSUFFICIENT_EVIDENCE,
            unresolved_claim_ids=[c.argument_id for c in twin_result.constructor_claims],
            decision_reasons=reasons, risk_state=risk_opinion.recommendation, confidence=0.2, epistemic_state="CONTESTED",
        )

    # 3. RiskCounsel recommends human approval -- Court cannot ACCEPT on
    # its own; the decision itself needs a human, not just more evidence.
    if risk_opinion.recommendation == "human_approval":
        reasons.extend(risk_opinion.reasons)
        return CourtVerdict(
            verdict=CourtVerdictState.INSUFFICIENT_EVIDENCE,
            unresolved_claim_ids=[c.argument_id for c in twin_result.constructor_claims],
            decision_reasons=reasons, risk_state=risk_opinion.recommendation, confidence=0.3, epistemic_state="CONTESTED",
        )

    all_claim_ids = {c.argument_id for c in twin_result.constructor_claims}
    disputed = set(twin_result.disputed_claim_ids)
    surviving = set(twin_result.surviving_claim_ids)

    # 4. Every claim disputed and none survive -> REJECT (if unsupported
    # assumptions/counter-evidence are present) or REVISE (disputed but
    # not conclusively broken).
    if disputed and not surviving:
        if twin_result.counter_evidence_ids or twin_result.unsupported_assumption_ids:
            reasons.append("all claims disputed, with real counter-evidence or unsupported assumptions found")
            return CourtVerdict(
                verdict=CourtVerdictState.REJECT, rejected_claim_ids=list(all_claim_ids),
                decision_reasons=reasons, risk_state=risk_opinion.recommendation, confidence=0.7, epistemic_state="DISPROVEN",
            )
        reasons.append("all claims disputed, but no confirmed counter-evidence -- needs revision, not outright rejection")
        return CourtVerdict(
            verdict=CourtVerdictState.REVISE, unresolved_claim_ids=list(all_claim_ids),
            required_revision="address Falsifier objections and re-cite stronger evidence", decision_reasons=reasons,
            risk_state=risk_opinion.recommendation, confidence=0.4, epistemic_state="CONTESTED",
        )

    # 5. Some disputed, some survive -> REVISE.
    if disputed and surviving:
        reasons.append(f"{len(disputed)} claim(s) disputed, {len(surviving)} survive -- revision needed on the disputed subset")
        return CourtVerdict(
            verdict=CourtVerdictState.REVISE, accepted_claim_ids=list(surviving), unresolved_claim_ids=list(disputed),
            required_revision="revise or drop the disputed claims; surviving claims may stand", decision_reasons=reasons,
            risk_state=risk_opinion.recommendation, confidence=0.6, epistemic_state="CONTESTED",
        )

    # 6. Nothing disputed -> ACCEPT, but evidence completeness still
    # informs confidence/epistemic_state honestly.
    if evidence_report.claims_missing_evidence:
        reasons.append(f"no claims disputed, but {len(evidence_report.claims_missing_evidence)} claim(s) cite no evidence")
        return CourtVerdict(
            verdict=CourtVerdictState.ACCEPT, accepted_claim_ids=list(all_claim_ids),
            decision_reasons=reasons, risk_state=risk_opinion.recommendation, confidence=0.6, epistemic_state="PROBABLE",
        )

    reasons.append("no claims disputed, all claims cite evidence, no unresolved critical contradiction")
    return CourtVerdict(
        verdict=CourtVerdictState.ACCEPT, accepted_claim_ids=list(all_claim_ids),
        decision_reasons=reasons, risk_state=risk_opinion.recommendation, confidence=0.85, epistemic_state="SUPPORTED",
    )
