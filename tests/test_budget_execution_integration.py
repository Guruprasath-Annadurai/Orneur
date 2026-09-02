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


@pytest.mark.asyncio
async def test_multiple_claims_do_not_spuriously_exhaust_verification_budget(monkeypatch):
    """Regression test for a real bug found live during Phase 7.1's own
    testing: the verification purpose's cap was originally sized as a
    small fixed PERCENTAGE of the total budget pool (verification's ~15%
    base weight), computed before claim count is known -- a request with
    several claims (extraction + 1 reservation per claim) could exceed
    that small cap and raise TruthBudgetExhaustedError even though the
    real shared CognitiveBudget had plenty of remaining capacity. Fixed by
    widening the verification cap to the full REMAINING budget capacity."""
    import orca.truth.claims as claims_mod
    import orca.truth.verification as verification_mod
    import orca.truth.contradiction as contradiction_mod
    import orca.truth.truth_fabric as truth_fabric_mod

    async def fake_extract(text, tier="nano"):
        from orca.truth.contracts import AtomicClaim
        return [AtomicClaim(claim_id=f"c{i}", text=f"claim {i}") for i in range(4)]  # 4 claims -> 5 total verification reservations (1 extraction + 4 claims)

    async def fake_verify_claim(claim_id, claim_text, evidence, tier="nano"):
        from orca.truth.contracts import ClaimSupport, ClaimSupportState
        return ClaimSupport(claim_id=claim_id, evidence_ids=[], support_state=ClaimSupportState.SUPPORTED)

    async def fake_detect_contradictions(claims, tier="nano"):
        return []

    for mod in (claims_mod, verification_mod, contradiction_mod, truth_fabric_mod):
        monkeypatch.setattr(mod, "extract_atomic_claims", fake_extract, raising=False)
        monkeypatch.setattr(mod, "verify_claim", fake_verify_claim, raising=False)
        monkeypatch.setattr(mod, "detect_contradictions", fake_detect_contradictions, raising=False)

    fabric = TruthFabric()
    # A small total budget (6, matching orca.cognitive.budget.DEFAULT_BUDGET)
    # -- verification's naive 15% slice would round to 1, well under the
    # 5 reservations this call actually needs.
    budget = CognitiveBudget(max_model_calls=6)
    result = await fabric.verify_answer("some answer", _prior_result(), budget=budget)
    assert result.evidence_state is not None
    assert budget.consumed_model_calls == 5
