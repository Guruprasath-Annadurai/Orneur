"""
Kernel-level Truth Fabric integration -- real Ollama, real DocStore (Phase 4
spec §46/§54 acceptance gates: "strict evidence requests use Truth Fabric",
"some audit-grade requests can succeed only with verified evidence",
"insufficient audit-grade requests abstain").

This exercises orca.cognitive.kernel.CognitiveKernel.execute(doc_store=...)
end to end -- plan() -> TruthFabric.assess_evidence() -> ModelGateway
answer -> TruthFabric.verify_answer() -- not just the individual Truth
Fabric modules in isolation (those are covered by
tests/test_truth_fabric_integration.py already).
"""
from __future__ import annotations

import uuid

import pytest

from orca.cognitive.contracts import AbstentionReason, CognitiveRequest, CognitiveState
from orca.cognitive.kernel import CognitiveKernel
from orca.docs.chunker import Chunk
from orca.docs.store import DocStore
from orca.gateway import wiring as gateway_wiring
from tests.ollama_test_support import require_ollama

pytestmark = pytest.mark.live_ollama_smoke


@pytest.fixture(autouse=True)
def _reset_gateway():
    gateway_wiring.reset_for_tests()
    yield
    gateway_wiring.reset_for_tests()


def _doc_store_with_evidence() -> DocStore:
    session_id = f"truth-fabric-kernel-test-{uuid.uuid4().hex[:8]}"
    store = DocStore(session_id=session_id)
    chunk = Chunk(
        text="The Eiffel Tower is 330 meters tall and located in Paris, France.",
        doc_id="d1", filename="facts.txt", chunk_idx=0, char_start=0, char_end=67,
    )
    store.add_chunks([chunk], doc_id="d1", filename="facts.txt")
    return store


@pytest.mark.asyncio
async def test_strict_evidence_request_answers_via_truth_fabric_with_doc_store():
    require_ollama()
    doc_store = _doc_store_with_evidence()
    kernel = CognitiveKernel()
    req = CognitiveRequest(
        objective="According to the documents, how tall is the Eiffel Tower and where is it located?",
    )
    result = await kernel.execute(req, doc_store=doc_store)
    assert result.status == CognitiveState.COMPLETED
    assert result.output is not None
    assert result.evidence_state is not None


@pytest.mark.asyncio
async def test_audit_grade_request_with_no_doc_store_abstains_insufficient_evidence():
    require_ollama()
    kernel = CognitiveKernel()
    req = CognitiveRequest(objective="How do I rm -rf the production database?")
    result = await kernel.execute(req)
    assert result.status == CognitiveState.ABSTAINED
    assert result.abstention_reason == AbstentionReason.INSUFFICIENT_EVIDENCE
    assert result.output is None
