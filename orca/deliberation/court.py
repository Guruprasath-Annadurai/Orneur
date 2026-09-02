"""
CognitiveCourt (Phase 6 spec §14-19; Phase 7 spec §41 Society integration).
Orchestrates the bounded roles: Constructor + Falsifier
(orca.deliberation.twin.EpistemicTwin), EvidenceClerk (reports on Truth
Fabric's own output, never re-verifies), RiskCounsel (recommends, never
authorizes), Arbiter (deterministic verdict aggregation, never a model
vote).

Truth Fabric remains the evidence authority (spec §38) -- CognitiveCourt
never builds a second retrieval/verification stack; it consumes a
TruthResult the caller already computed via TruthFabric.assess_evidence()/
verify_answer().

Phase 7: Constructor/Falsifier model selection is resolved through
Model Society routing (orca.society.society_plan.build_court_society_plan)
instead of a hardcoded tier literal -- Court no longer resolves `"nano"`
directly (spec §41). Budget consumption for the round is metered through
`orca.society.budget_ledger.SocietyBudgetLedger`, operationalizing the
Phase 6 Cognitive Budget Market policy instead of a flat, decorative
`consume(MODEL_CALLS, 2)` (spec §24-25). A request-scoped WorldState is
built from the TruthResult and attached to the case (spec §28).
"""
from __future__ import annotations

import asyncio

from orca.cognitive.budget import CognitiveBudgetExhaustedError
from orca.cognitive.contracts import BudgetDimension, CognitiveBudget, RiskLevel
from orca.deliberation.arbiter import arbitrate
from orca.deliberation.budget_market import allocate_budget
from orca.deliberation.contracts import ComplexityLevel, CourtCase, CourtVerdict, CourtVerdictState
from orca.deliberation.evidence_clerk import build_evidence_report
from orca.deliberation.risk_counsel import assess_risk_opinion
from orca.deliberation.twin import EpistemicTwin
from orca.deliberation.worldstate_build import build_world_state
from orca.deliberation.worldstate_ops import unavailable_model_ids
from orca.society.budget_ledger import SocietyBudgetLedger
from orca.society.disagreement import compute_disagreement
from orca.society.router import model_id_to_tier
from orca.society.society_plan import build_court_society_plan

COURT_DEADLINE_S = 60.0


class CognitiveCourt:
    def __init__(self, twin: EpistemicTwin | None = None, allow_experimental_models: bool = False):
        """`twin`, when given explicitly, bypasses Society routing entirely
        (used by tests that want a fixed tier) -- production callers should
        leave this None so Court routes Constructor/Falsifier through
        Model Society (spec §41)."""
        self._explicit_twin = twin
        self.allow_experimental_models = allow_experimental_models

    async def run(
        self, objective: str, *, truth_result=None, risk_level: RiskLevel = RiskLevel.LOW,
        audit_grade: bool = False, budget: CognitiveBudget | None = None,
        allowed_capability_classes: list[str] | None = None,
        initial_world_state=None,
    ) -> tuple[CourtCase, CourtVerdict, str]:
        """Returns (case, verdict, stop_reason). Bounded to one
        Constructor+Falsifier round in this first production version
        (spec §30/§14) -- exactly 2 model calls, both budget-metered.
        Never blocks indefinitely: a hard OVERALL deadline wraps the
        whole call."""
        evidence_texts = [
            (ev.evidence_id, ev.passage.text) for ev in (getattr(truth_result, "evidence", None) or [])
        ]

        # WorldState is built BEFORE routing this phase (Phase 7.1 spec
        # §12-13) so a caller-recorded model-unavailability observation can
        # actually change the routing decision, not just be recorded
        # after the fact.
        world_state = build_world_state(objective, truth_result=truth_result)
        if initial_world_state is not None:
            # A caller (Kernel, or a tool-observation hook) may seed
            # observations made BEFORE this Court invocation started --
            # e.g. "deployment X went unhealthy mid-session" (spec §13's
            # own worked example). Merged, never overwritten: an entity
            # already present in the freshly-built state is not clobbered.
            for entity, info in initial_world_state.variables.items():
                world_state.variables.setdefault(entity, info)
            world_state.update_log.extend(initial_world_state.update_log)
        excluded_model_ids = unavailable_model_ids(world_state)

        if self._explicit_twin is not None:
            twin = self._explicit_twin
            constructor_tier = falsifier_tier = None
            same_model_overlap = True
            routing_decision_ids: list[str] = []
        else:
            plan = build_court_society_plan(
                risk_level=risk_level.value, allow_experimental=self.allow_experimental_models,
                allowed_capability_classes=allowed_capability_classes or [],
                exclude_model_ids=excluded_model_ids,
            )
            constructor_decision = plan.assignments[0].routing_decision
            falsifier_decision = plan.assignments[1].routing_decision
            if constructor_decision.selected_model_id is None or falsifier_decision.selected_model_id is None:
                verdict = CourtVerdict(
                    verdict=CourtVerdictState.INSUFFICIENT_EVIDENCE,
                    decision_reasons=["Model Society found no eligible model for Constructor/Falsifier"],
                    epistemic_state="UNVERIFIED",
                )
                case = CourtCase(
                    objective=objective, risk_level=risk_level, world_state=world_state,
                    routing_decision_ids=[constructor_decision.decision_id, falsifier_decision.decision_id],
                )
                return case, verdict, "COURT_INSUFFICIENT_EVIDENCE"
            constructor_tier = model_id_to_tier(constructor_decision.selected_model_id)
            falsifier_tier = model_id_to_tier(falsifier_decision.selected_model_id)
            twin = EpistemicTwin(
                tier=constructor_tier,
                constructor_checkpoint=constructor_decision.selected_checkpoint_id or "",
                falsifier_checkpoint=falsifier_decision.selected_checkpoint_id or "",
            )
            same_model_overlap = plan.same_model_role_overlap
            routing_decision_ids = [constructor_decision.decision_id, falsifier_decision.decision_id]

        if budget is not None:
            allocation = allocate_budget(
                uncertainty=0.5, risk=risk_level, evidence_conflict=bool(getattr(truth_result, "contradictions", None)),
                complexity=ComplexityLevel.MEDIUM,
            )
            ledger = SocietyBudgetLedger(budget=budget, allocation=allocation)
            try:
                constructor_reservation = ledger.reserve("constructor", 1)
                falsifier_reservation = ledger.reserve("falsifier", 1)
            except CognitiveBudgetExhaustedError:
                verdict = CourtVerdict(
                    verdict=CourtVerdictState.INSUFFICIENT_EVIDENCE,
                    decision_reasons=["Court budget exhausted before Constructor/Falsifier could run"],
                    epistemic_state="UNVERIFIED",
                )
                case = CourtCase(objective=objective, risk_level=risk_level, world_state=world_state)
                return case, verdict, "DELIBERATION_BUDGET_EXHAUSTED"
        else:
            constructor_reservation = falsifier_reservation = None

        try:
            twin_result = await asyncio.wait_for(
                twin.run(objective, evidence_texts, constructor_tier=constructor_tier, falsifier_tier=falsifier_tier),
                timeout=COURT_DEADLINE_S,
            )
        except asyncio.TimeoutError:
            if budget is not None and constructor_reservation is not None:
                ledger.release_reservation(constructor_reservation)
                ledger.release_reservation(falsifier_reservation)
            verdict = CourtVerdict(
                verdict=CourtVerdictState.INSUFFICIENT_EVIDENCE,
                decision_reasons=[f"Court exceeded its {COURT_DEADLINE_S}s deadline"], epistemic_state="UNVERIFIED",
            )
            case = CourtCase(objective=objective, risk_level=risk_level, world_state=world_state)
            return case, verdict, "DEADLINE_REACHED"

        evidence_report = build_evidence_report(twin_result.constructor_claims, truth_result)
        risk_opinion = assess_risk_opinion(risk_level, evidence_report, twin_result.unresolved_questions)
        verdict = arbitrate(twin_result, evidence_report, risk_opinion, audit_grade=audit_grade)
        disagreement = compute_disagreement(twin_result)

        contradictions = list(getattr(truth_result, "contradictions", None) or [])
        evidence_state = getattr(getattr(truth_result, "evidence_state", None), "value", None)
        case = CourtCase(
            objective=objective, contradictions=contradictions, evidence_state=evidence_state,
            risk_level=risk_level, arguments=twin_result.constructor_claims,
            counter_arguments=twin_result.falsifier_objections, role_executions=twin_result.role_executions,
            world_state=world_state, same_model_role_overlap=same_model_overlap,
            routing_decision_ids=routing_decision_ids,
            disagreement_severity=disagreement.severity, disagreement_types=[t.value for t in disagreement.types],
        )

        stop_reason = {
            CourtVerdictState.ACCEPT: "COURT_ACCEPTED",
            CourtVerdictState.REJECT: "COURT_REJECTED",
            CourtVerdictState.REVISE: "REVISION_REQUIRED",
            CourtVerdictState.INSUFFICIENT_EVIDENCE: "COURT_INSUFFICIENT_EVIDENCE",
        }[verdict.verdict]
        return case, verdict, stop_reason
