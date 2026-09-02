"""
TruthFabric end-to-end integration -- real, non-mocked Gateway/Ollama
calls where safe (Phase 4 spec §46, matching this project's standing
"do not rely only on mocked model behavior" discipline). Classified
live_ollama_smoke (Phase 3.2 test policy).
"""
from __future__ import annotations

import asyncio

import pytest

from orca.cognitive.contracts import ComplexityLevel, EvidenceLevel, FreshnessLevel
from orca.cognitive.intent import compile_intent
from orca.gateway import wiring as gateway_wiring
from orca.truth.contracts import EvidenceState, TruthRequest
from orca.truth.truth_fabric import TruthFabric
from tests.ollama_test_support import require_ollama, warm_model

pytestmark = pytest.mark.live_ollama_smoke


@pytest.fixture(autouse=True)
def _reset_gateway():
    gateway_wiring.reset_for_tests()
    yield
    gateway_wiring.reset_for_tests()


def _make_doc_store(session_id: str, text: str, filename: str = "facts.txt"):
    from orca.docs import DocStore, chunk_text

    store = DocStore(session_id=session_id, ollama_host="http://localhost:11434")
    chunks = chunk_text(text, doc_id="doc-1", filename=filename)
    store.add_chunks(chunks, doc_id="doc-1", filename=filename)
    return store


@pytest.mark.asyncio
async def test_assess_evidence_finds_real_document_evidence():
    require_ollama()
    store = _make_doc_store("truth-test-1", "The Eiffel Tower is located in Paris, France. It was completed in 1889.")
    fabric = TruthFabric()
    objective = "Where is the Eiffel Tower located?"
    intent = compile_intent(objective)
    req = TruthRequest(objective=objective, evidence_requirement=EvidenceLevel.SUPPORTED, freshness_requirement=FreshnessLevel.STATIC)
    result = await fabric.assess_evidence(req, intent, ComplexityLevel.LOW, doc_store=store)
    assert result.evidence_state == EvidenceState.SUFFICIENT
    assert len(result.evidence) > 0
    assert result.sources


@pytest.mark.asyncio
async def test_assess_evidence_insufficient_with_no_doc_store():
    require_ollama()
    fabric = TruthFabric()
    objective = "What is the internal code name for our unreleased product?"
    intent = compile_intent(objective)
    req = TruthRequest(objective=objective, evidence_requirement=EvidenceLevel.SUPPORTED, freshness_requirement=FreshnessLevel.STATIC)
    result = await fabric.assess_evidence(req, intent, ComplexityLevel.LOW, doc_store=None)
    assert result.evidence_state == EvidenceState.INSUFFICIENT
    assert result.evidence == []


@pytest.mark.asyncio
async def test_verify_answer_supports_a_grounded_claim():
    require_ollama()
    warm_model("nano")
    store = _make_doc_store("truth-test-2", "The Eiffel Tower is located in Paris, France. It was completed in 1889.")
    fabric = TruthFabric()
    objective = "Where is the Eiffel Tower located?"
    intent = compile_intent(objective)
    req = TruthRequest(objective=objective, evidence_requirement=EvidenceLevel.SUPPORTED, freshness_requirement=FreshnessLevel.STATIC)
    assessed = await fabric.assess_evidence(req, intent, ComplexityLevel.LOW, doc_store=store)

    final = await fabric.verify_answer("The Eiffel Tower is located in Paris, France.", assessed)
    assert final.claims
    assert any(s.support_state.value == "SUPPORTED" for s in final.claim_supports)
    assert final.citation_coverage["citation_coverage_ratio"] > 0
    assert final.citation_verdicts  # only accepted (supported/partial) verdicts are ever returned here


@pytest.mark.asyncio
async def test_verify_answer_never_fabricates_support_for_unrelated_claim():
    require_ollama()
    warm_model("nano")
    store = _make_doc_store("truth-test-3", "The Eiffel Tower is located in Paris, France. It was completed in 1889.")
    fabric = TruthFabric()
    objective = "Where is the Eiffel Tower located?"
    intent = compile_intent(objective)
    req = TruthRequest(objective=objective, evidence_requirement=EvidenceLevel.SUPPORTED, freshness_requirement=FreshnessLevel.STATIC)
    assessed = await fabric.assess_evidence(req, intent, ComplexityLevel.LOW, doc_store=store)

    final = await fabric.verify_answer("The Great Wall of China is over 13,000 miles long.", assessed)
    assert final.claims
    assert not any(s.support_state.value == "SUPPORTED" for s in final.claim_supports)


@pytest.mark.asyncio
async def test_budget_exhaustion_stops_truth_fabric_explicitly():
    from orca.cognitive.contracts import CognitiveBudget
    from orca.truth.errors import TruthBudgetExhaustedError

    require_ollama()
    store = _make_doc_store("truth-test-4", "Some real fact text to retrieve.")
    fabric = TruthFabric()
    objective = "What is the fact?"
    intent = compile_intent(objective)
    req = TruthRequest(objective=objective, evidence_requirement=EvidenceLevel.SUPPORTED, freshness_requirement=FreshnessLevel.STATIC)
    exhausted_budget = CognitiveBudget(max_retrieval_calls=0)

    with pytest.raises(TruthBudgetExhaustedError):
        await fabric.assess_evidence(req, intent, ComplexityLevel.LOW, doc_store=store, budget=exhausted_budget)


@pytest.mark.asyncio
async def test_cancellation_propagates_through_truth_fabric():
    """Phase 4 spec §41: cancellation must propagate through Truth Fabric
    to search/retrieval/fetch/verifier/ModelGateway, not leave orphan
    background tasks running."""
    require_ollama()
    warm_model("nano")
    store = _make_doc_store("truth-test-5", "The Eiffel Tower is located in Paris, France.")
    fabric = TruthFabric()
    objective = "Where is the Eiffel Tower located?"
    intent = compile_intent(objective)
    req = TruthRequest(objective=objective, evidence_requirement=EvidenceLevel.SUPPORTED, freshness_requirement=FreshnessLevel.STATIC)
    assessed = await fabric.assess_evidence(req, intent, ComplexityLevel.LOW, doc_store=store)

    task = asyncio.create_task(fabric.verify_answer("The Eiffel Tower is in Paris.", assessed))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
