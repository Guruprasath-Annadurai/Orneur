"""
Phase 7.1 spec §15-19: CognitiveKernel must actually wire the bounded
replanning mechanism into its production path -- a Court REVISE verdict
triggers ONE bounded plan revision + Court re-run, never an unbounded
loop, and a persistent REVISE past MAX_REPLANS degrades to proceeding
rather than looping forever.

Deterministic -- Court, Truth Fabric, and model generation are all
monkeypatched so this test needs no live Ollama instance, while the
Kernel's OWN replan-loop code (orca/cognitive/kernel.py) runs for real.
"""
from __future__ import annotations

import pytest

from orca.cognitive.contracts import CognitiveRequest, CognitiveState
from orca.cognitive.kernel import CognitiveKernel
from orca.deliberation.contracts import CourtCase, CourtVerdict, CourtVerdictState
from orca.deliberation.replanning import MAX_REPLANS
from orca.truth.contracts import EvidenceState, TruthResult


def _fake_truth_result(request_id="r1") -> TruthResult:
    return TruthResult(request_id=request_id, trace_id=None, evidence_state=EvidenceState.SUFFICIENT, evidence=[], sources=[])


@pytest.mark.asyncio
async def test_court_revise_triggers_exactly_one_bounded_replan_then_accept(monkeypatch):
    import orca.cognitive.kernel as kernel_mod
    import orca.deliberation.court as court_mod
    import orca.truth.truth_fabric as truth_mod

    verdict_sequence = [CourtVerdictState.REVISE, CourtVerdictState.ACCEPT]
    call_count = {"n": 0}

    async def fake_court_run(self, objective, **kwargs):
        verdict_state = verdict_sequence[min(call_count["n"], len(verdict_sequence) - 1)]
        call_count["n"] += 1
        case = CourtCase(objective=objective)
        verdict = CourtVerdict(verdict=verdict_state, epistemic_state="VERIFIED")
        stop_reason = {"REVISE": "REVISION_REQUIRED", "ACCEPT": "COURT_ACCEPTED"}[verdict_state.value]
        return case, verdict, stop_reason

    monkeypatch.setattr(court_mod.CognitiveCourt, "run", fake_court_run)

    async def fake_assess_evidence(self, *args, **kwargs):
        from orca.truth.contracts import Contradiction, ContradictionRelationship
        result = _fake_truth_result()
        result.contradictions = [Contradiction(claim_a_id="a", claim_b_id="b", relationship=ContradictionRelationship.DIRECT_CONTRADICTION)]
        return result

    async def fake_verify_answer(self, *args, **kwargs):
        return _fake_truth_result()

    monkeypatch.setattr(truth_mod.TruthFabric, "assess_evidence", fake_assess_evidence)
    monkeypatch.setattr(truth_mod.TruthFabric, "verify_answer", fake_verify_answer)

    async def fake_answer_directly(self, objective, tier, trace_id):
        return "A deterministic canned answer.", "orneur-genesis", {"prompt_tokens": 1, "completion_tokens": 1}

    monkeypatch.setattr(kernel_mod.CognitiveKernel, "_answer_directly", fake_answer_directly)

    kernel = CognitiveKernel()
    req = CognitiveRequest(objective="According to the documents, how tall is the Eiffel Tower and where is it located?")
    from orca.docs.store import DocStore
    result = await kernel.execute(req, doc_store=DocStore(session_id="replan-test"))

    assert call_count["n"] == 2  # exactly one REVISE-triggered replan, then ACCEPT
    assert result.status == CognitiveState.COMPLETED


@pytest.mark.asyncio
async def test_persistent_revise_degrades_after_max_replans_instead_of_looping_forever(monkeypatch):
    import orca.cognitive.kernel as kernel_mod
    import orca.deliberation.court as court_mod
    import orca.truth.truth_fabric as truth_mod

    call_count = {"n": 0}

    async def fake_court_run(self, objective, **kwargs):
        call_count["n"] += 1
        case = CourtCase(objective=objective)
        verdict = CourtVerdict(verdict=CourtVerdictState.REVISE, epistemic_state="UNVERIFIED")
        return case, verdict, "REVISION_REQUIRED"

    monkeypatch.setattr(court_mod.CognitiveCourt, "run", fake_court_run)

    async def fake_assess_evidence(self, *args, **kwargs):
        from orca.truth.contracts import Contradiction, ContradictionRelationship
        result = _fake_truth_result()
        result.contradictions = [Contradiction(claim_a_id="a", claim_b_id="b", relationship=ContradictionRelationship.DIRECT_CONTRADICTION)]
        return result

    async def fake_verify_answer(self, *args, **kwargs):
        return _fake_truth_result()

    monkeypatch.setattr(truth_mod.TruthFabric, "assess_evidence", fake_assess_evidence)
    monkeypatch.setattr(truth_mod.TruthFabric, "verify_answer", fake_verify_answer)

    async def fake_answer_directly(self, objective, tier, trace_id):
        return "A deterministic canned answer.", "orneur-genesis", {"prompt_tokens": 1, "completion_tokens": 1}

    monkeypatch.setattr(kernel_mod.CognitiveKernel, "_answer_directly", fake_answer_directly)

    kernel = CognitiveKernel()
    req = CognitiveRequest(objective="According to the documents, how tall is the Eiffel Tower and where is it located?")
    from orca.docs.store import DocStore
    result = await kernel.execute(req, doc_store=DocStore(session_id="replan-bound-test"))

    # MAX_REPLANS bounded revisions + 1 final call that proceeds despite
    # still being REVISE -- never an unbounded loop.
    assert call_count["n"] == MAX_REPLANS + 1
    assert result.status == CognitiveState.COMPLETED
