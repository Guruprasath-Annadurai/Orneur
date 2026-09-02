"""
CognitiveCourt (Phase 6 spec §14-19). Orchestrates the bounded roles:
Constructor + Falsifier (orca.deliberation.twin.EpistemicTwin),
EvidenceClerk (reports on Truth Fabric's own output, never re-verifies),
RiskCounsel (recommends, never authorizes), Arbiter (deterministic
verdict aggregation, never a model vote).

Truth Fabric remains the evidence authority (spec §38) -- CognitiveCourt
never builds a second retrieval/verification stack; it consumes a
TruthResult the caller already computed via TruthFabric.assess_evidence()/
verify_answer().
"""
from __future__ import annotations

import asyncio
import time

from orca.cognitive.budget import CognitiveBudgetExhaustedError, consume
from orca.cognitive.contracts import BudgetDimension, CognitiveBudget, RiskLevel
from orca.deliberation.arbiter import arbitrate
from orca.deliberation.contracts import CourtCase, CourtVerdict, CourtVerdictState
from orca.deliberation.evidence_clerk import build_evidence_report
from orca.deliberation.risk_counsel import assess_risk_opinion
from orca.deliberation.twin import EpistemicTwin

COURT_DEADLINE_S = 60.0


class CognitiveCourt:
    def __init__(self, twin: EpistemicTwin | None = None):
        self.twin = twin or EpistemicTwin()

    async def run(
        self, objective: str, *, truth_result=None, risk_level: RiskLevel = RiskLevel.LOW,
        audit_grade: bool = False, budget: CognitiveBudget | None = None,
    ) -> tuple[CourtCase, CourtVerdict, str]:
        """Returns (case, verdict, stop_reason). Bounded to one
        Constructor+Falsifier round in this first production version
        (spec §30/§14) -- exactly 2 model calls, both budget-metered.
        Never blocks indefinitely: a hard OVERALL deadline wraps the
        whole call."""
        evidence_texts = [
            (ev.evidence_id, ev.passage.text) for ev in (getattr(truth_result, "evidence", None) or [])
        ]

        if budget is not None:
            try:
                consume(budget, BudgetDimension.MODEL_CALLS, 2)   # Constructor + Falsifier, charged up front
            except CognitiveBudgetExhaustedError:
                verdict = CourtVerdict(
                    verdict=CourtVerdictState.INSUFFICIENT_EVIDENCE,
                    decision_reasons=["Court budget exhausted before Constructor/Falsifier could run"],
                    epistemic_state="UNVERIFIED",
                )
                case = CourtCase(objective=objective, risk_level=risk_level)
                return case, verdict, "DELIBERATION_BUDGET_EXHAUSTED"

        try:
            twin_result = await asyncio.wait_for(self.twin.run(objective, evidence_texts), timeout=COURT_DEADLINE_S)
        except asyncio.TimeoutError:
            verdict = CourtVerdict(
                verdict=CourtVerdictState.INSUFFICIENT_EVIDENCE,
                decision_reasons=[f"Court exceeded its {COURT_DEADLINE_S}s deadline"], epistemic_state="UNVERIFIED",
            )
            case = CourtCase(objective=objective, risk_level=risk_level)
            return case, verdict, "DEADLINE_REACHED"

        evidence_report = build_evidence_report(twin_result.constructor_claims, truth_result)
        risk_opinion = assess_risk_opinion(risk_level, evidence_report, twin_result.unresolved_questions)
        verdict = arbitrate(twin_result, evidence_report, risk_opinion, audit_grade=audit_grade)

        contradictions = list(getattr(truth_result, "contradictions", None) or [])
        evidence_state = getattr(getattr(truth_result, "evidence_state", None), "value", None)
        case = CourtCase(
            objective=objective, contradictions=contradictions, evidence_state=evidence_state,
            risk_level=risk_level, arguments=twin_result.constructor_claims,
            counter_arguments=twin_result.falsifier_objections, role_executions=twin_result.role_executions,
        )

        stop_reason = {
            CourtVerdictState.ACCEPT: "COURT_ACCEPTED",
            CourtVerdictState.REJECT: "COURT_REJECTED",
            CourtVerdictState.REVISE: "REVISION_REQUIRED",
            CourtVerdictState.INSUFFICIENT_EVIDENCE: "COURT_INSUFFICIENT_EVIDENCE",
        }[verdict.verdict]
        return case, verdict, stop_reason
