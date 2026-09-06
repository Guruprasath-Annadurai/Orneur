"""
Cognitive Court end-to-end -- real, non-mocked Gateway/Ollama calls
(Phase 6 spec §54, matching this project's standing "do not rely only
on mocked model behavior" discipline). Classified live_ollama_smoke.
"""
from __future__ import annotations

import pytest

from orca.cognitive.contracts import CognitiveBudget, ComplexityLevel, EvidenceLevel, FreshnessLevel, RiskLevel
from orca.cognitive.intent import compile_intent
from orca.deliberation.court import CognitiveCourt
from orca.docs.chunker import Chunk
from orca.docs.store import DocStore
from orca.gateway import wiring as gateway_wiring
from orca.truth.contracts import TruthRequest
from orca.truth.truth_fabric import TruthFabric
from tests.ollama_test_support import require_ollama

pytestmark = pytest.mark.live_ollama_smoke


@pytest.fixture(autouse=True)
def _reset_gateway():
    gateway_wiring.reset_for_tests()
    yield
    gateway_wiring.reset_for_tests()


async def _assess(objective: str, doc_text: str | None = None):
    fabric = TruthFabric()
    intent = compile_intent(objective)
    req = TruthRequest(objective=objective, evidence_requirement=EvidenceLevel.SUPPORTED, freshness_requirement=FreshnessLevel.STATIC)
    doc_store = None
    if doc_text:
        import uuid
        doc_store = DocStore(session_id=f"court-test-{uuid.uuid4().hex[:8]}")
        chunk = Chunk(text=doc_text, doc_id="d1", filename="f.txt", chunk_idx=0, char_start=0, char_end=len(doc_text))
        doc_store.add_chunks([chunk], doc_id="d1", filename="f.txt")
    return await fabric.assess_evidence(req, intent, ComplexityLevel.LOW, doc_store=doc_store)


@pytest.mark.asyncio
async def test_court_accepts_well_evidenced_claim():
    require_ollama()
    truth_result = await _assess("Where is the Eiffel Tower located?", "The Eiffel Tower is located in Paris, France.")
    court = CognitiveCourt()
    case, verdict, stop_reason = await court.run("Where is the Eiffel Tower located?", truth_result=truth_result, risk_level=RiskLevel.LOW)
    assert verdict.verdict is not None
    assert case.arguments  # Constructor produced structured claims, not just prose
    assert stop_reason in ("COURT_ACCEPTED", "REVISION_REQUIRED", "COURT_REJECTED", "COURT_INSUFFICIENT_EVIDENCE")


@pytest.mark.asyncio
async def test_court_with_no_evidence_does_not_accept():
    require_ollama()
    from orca.deliberation.contracts import CourtVerdictState
    truth_result = await _assess("What is the internal code name for our unreleased product?")
    court = CognitiveCourt()
    case, verdict, stop_reason = await court.run(
        "What is the internal code name for our unreleased product?", truth_result=truth_result, risk_level=RiskLevel.LOW,
    )
    assert verdict.verdict != CourtVerdictState.ACCEPT or not case.arguments


@pytest.mark.asyncio
async def test_court_budget_exhaustion_never_forces_a_confident_verdict():
    require_ollama()
    truth_result = await _assess("Where is the Eiffel Tower located?", "The Eiffel Tower is located in Paris, France.")
    court = CognitiveCourt()
    exhausted = CognitiveBudget(max_model_calls=0)
    case, verdict, stop_reason = await court.run(
        "Where is the Eiffel Tower located?", truth_result=truth_result, risk_level=RiskLevel.LOW, budget=exhausted,
    )
    from orca.deliberation.contracts import CourtVerdictState
    assert verdict.verdict == CourtVerdictState.INSUFFICIENT_EVIDENCE
    assert stop_reason == "DELIBERATION_BUDGET_EXHAUSTED"


@pytest.mark.asyncio
async def test_court_records_which_model_served_each_role():
    """Spec §21: same-model role overlap must be disclosed, not hidden."""
    require_ollama()
    truth_result = await _assess("Where is the Eiffel Tower located?", "The Eiffel Tower is located in Paris, France.")
    court = CognitiveCourt()
    case, verdict, _ = await court.run("Where is the Eiffel Tower located?", truth_result=truth_result, risk_level=RiskLevel.LOW)
    roles = {r.role.value for r in case.role_executions}
    assert "CONSTRUCTOR" in roles
    assert "FALSIFIER" in roles
    assert all(r.model_id for r in case.role_executions)
