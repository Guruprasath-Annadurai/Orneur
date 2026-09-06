"""
Phase 7.2 spec §7-10, §14: retrieval and counter-evidence operations must
reserve the correct RETRIEVAL_CALLS-dimension budget BEFORE running (never
run-then-account), corrective/multi-hop retrieval must share ONE parent
allocation, and counter-evidence must never report RAN when its
reservation failed. Deterministic -- search/doc-store calls monkeypatched.
"""
from __future__ import annotations

import pytest

from orca.cognitive.contracts import CognitiveBudget
from orca.truth.contracts import CounterEvidenceStatus
from orca.truth.counter_evidence import find_counter_evidence
from orca.truth.errors import TruthBudgetExhaustedError


class _FakeSearchProvider:
    def search(self, query, k):
        return []


@pytest.mark.asyncio
async def test_counter_evidence_reserves_before_searching_and_reports_budget_exhausted_not_ran():
    budget = CognitiveBudget(max_retrieval_calls=0)
    from orca.deliberation.budget_market import allocate_budget
    from orca.cognitive.contracts import RiskLevel, ComplexityLevel
    from orca.society.budget_ledger import SocietyBudgetLedger

    allocation = allocate_budget(uncertainty=0.5, risk=RiskLevel.LOW, evidence_conflict=False, complexity=ComplexityLevel.MEDIUM)
    ledger = SocietyBudgetLedger(budget=budget, allocation=allocation)
    ledger.caps["counter_evidence"] = 0  # explicitly no capacity

    result = await find_counter_evidence("some claim", _FakeSearchProvider(), budget=budget, retrieval_ledger=ledger)
    assert result.status == CounterEvidenceStatus.BUDGET_EXHAUSTED
    assert result.status != CounterEvidenceStatus.RAN


@pytest.mark.asyncio
async def test_counter_evidence_runs_and_consumes_retrieval_calls_dimension_not_model_calls():
    budget = CognitiveBudget(max_retrieval_calls=4, max_model_calls=0)  # zero MODEL_CALLS on purpose
    result = await find_counter_evidence("some claim", _FakeSearchProvider(), budget=budget)
    assert result.status == CounterEvidenceStatus.RAN  # succeeds even with zero MODEL_CALLS capacity
    assert budget.consumed_retrieval_calls == 1
    assert budget.consumed_model_calls == 0


@pytest.mark.asyncio
async def test_retrieval_reservation_happens_before_the_retrieve_call_not_after(monkeypatch):
    """A budget with zero retrieval capacity must prevent the retrieval
    call from executing at all -- proven by a doc_store.retrieve that
    would raise AssertionError if ever actually called."""
    import orca.truth.truth_fabric as truth_fabric_mod
    from orca.truth.contracts import TruthRequest, EvidenceLevel, FreshnessLevel

    class _FailingDocStore:
        def count(self):
            return 1

        def retrieve(self, q, max_documents):
            raise AssertionError("retrieval must not execute when budget is exhausted")

    fabric = truth_fabric_mod.TruthFabric()
    budget = CognitiveBudget(max_retrieval_calls=0, max_model_calls=6)
    request = TruthRequest(objective="According to the documents, what is the answer?", evidence_requirement=EvidenceLevel.STRICT, freshness_requirement=FreshnessLevel.STATIC)

    from orca.cognitive.contracts import IntentPlan, IntentCategory, ComplexityAssessment, ComplexityLevel

    intent = IntentPlan(primary_intent=IntentCategory.FACTUAL)
    complexity = ComplexityAssessment(level=ComplexityLevel.LOW, score=0.1)

    with pytest.raises(TruthBudgetExhaustedError):
        await fabric.assess_evidence(request, intent, complexity, doc_store=_FailingDocStore(), budget=budget)
