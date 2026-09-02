"""
Phase 7.1 spec §20-24: the Cognitive Budget Market's "verification" and
"replanning" purposes now have REAL enforcement effect against the shared
`CognitiveBudget`, not just a decorative allocation. Deterministic --
Truth Fabric's model calls and Court are monkeypatched.
"""
from __future__ import annotations

import pytest

from orca.cognitive.contracts import CognitiveBudget
from orca.truth.contracts import EvidenceState, TruthResult
from orca.truth.errors import TruthBudgetExhaustedError
from orca.truth.truth_fabric import TruthFabric


def _prior_result() -> TruthResult:
    return TruthResult(request_id="r1", trace_id=None, evidence_state=EvidenceState.SUFFICIENT, evidence=[], sources=[])


@pytest.mark.asyncio
async def test_verify_answer_raises_when_verification_budget_exhausted(monkeypatch):
    """A budget with zero MODEL_CALLS capacity must cause verify_answer to
    raise TruthBudgetExhaustedError from the verification-purpose
    reservation -- never silently skip verification and proceed as if it
    ran (spec §27's "stop optional role calls... do not silently exceed
    caps")."""
    import orca.truth.claims as claims_mod

    async def fake_extract(text, tier="nano"):
        from orca.truth.contracts import AtomicClaim
        return [AtomicClaim(claim_id="c1", text="a claim")]

    monkeypatch.setattr(claims_mod, "extract_atomic_claims", fake_extract)

    fabric = TruthFabric()
    exhausted_budget = CognitiveBudget(max_model_calls=0)

    with pytest.raises(TruthBudgetExhaustedError):
        await fabric.verify_answer("some answer", _prior_result(), budget=exhausted_budget)


@pytest.mark.asyncio
async def test_verify_answer_succeeds_with_sufficient_verification_budget(monkeypatch):
    import orca.truth.claims as claims_mod
    import orca.truth.verification as verification_mod
    import orca.truth.contradiction as contradiction_mod

    async def fake_extract(text, tier="nano"):
        from orca.truth.contracts import AtomicClaim
        return [AtomicClaim(claim_id="c1", text="a claim")]

    async def fake_verify_claim(claim_id, claim_text, evidence, tier="nano"):
        from orca.truth.contracts import ClaimSupport, ClaimSupportState
        return ClaimSupport(claim_id=claim_id, evidence_ids=[], support_state=ClaimSupportState.SUPPORTED)

    async def fake_detect_contradictions(claims, tier="nano"):
        return []

    monkeypatch.setattr(claims_mod, "extract_atomic_claims", fake_extract)
    monkeypatch.setattr(verification_mod, "verify_claim", fake_verify_claim)
    monkeypatch.setattr(contradiction_mod, "detect_contradictions", fake_detect_contradictions)

    import orca.truth.truth_fabric as truth_fabric_mod
    monkeypatch.setattr(truth_fabric_mod, "extract_atomic_claims", fake_extract)
    monkeypatch.setattr(truth_fabric_mod, "verify_claim", fake_verify_claim)
    monkeypatch.setattr(truth_fabric_mod, "detect_contradictions", fake_detect_contradictions)

    fabric = TruthFabric()
    budget = CognitiveBudget(max_model_calls=10)
    result = await fabric.verify_answer("some answer", _prior_result(), budget=budget)
    assert result.evidence_state is not None
    assert budget.consumed_model_calls > 0  # real consumption happened, not decorative
