"""
Bounded FIND_COUNTER_EVIDENCE hook (Phase 4.1 spec §16-17). Explicitly
NOT the Epistemic Twin -- no autonomous agent swarm, no open-ended
adversarial research. Exactly one bounded adversarial search query per
call, consuming CognitiveBudget like any other Truth Fabric operation,
and always honest about whether it actually ran.
"""
from __future__ import annotations

import asyncio

from orca.cognitive.budget import CognitiveBudgetExhaustedError, consume
from orca.cognitive.contracts import BudgetDimension, CognitiveBudget
from orca.truth import evidence as evidence_mod
from orca.truth.contracts import CounterEvidenceResult, CounterEvidenceStatus, Evidence
from orca.truth.search_provider import SearchProvider

COUNTER_EVIDENCE_TIMEOUT_S = 10.0


async def find_counter_evidence(
    claim_text: str, search_provider: SearchProvider, *, budget: CognitiveBudget | None = None, retrieval_ledger=None,
) -> CounterEvidenceResult:
    """
    Issues ONE bounded adversarial query ("evidence against: <claim>") --
    never a family of unbounded follow-ups, never an autonomous loop that
    decides for itself whether to keep searching. If the budget can't
    afford it, returns NOT_RUN (spec §17: "If unavailable due budget:
    record COUNTER_EVIDENCE_NOT_RUN. Do not pretend it was performed.")
    rather than silently skipping with no trace.

    Phase 7.2 spec §10: reserves against the `"counter_evidence"` purpose
    of a shared `SocietyBudgetLedger` (RETRIEVAL_CALLS -- this function is
    pure retrieval; no model/judge step exists here at all, per
    BUDGET_DIMENSION_AUDIT.md's finding) when `retrieval_ledger` is given,
    falling back to a direct `RETRIEVAL_CALLS` consume otherwise. Never
    reports `RAN` when the reservation itself failed (spec §10's explicit
    "do not report COUNTER_EVIDENCE_RAN when the operation did not
    actually run").
    """
    query = f"evidence against: {claim_text}"

    if retrieval_ledger is not None:
        try:
            retrieval_ledger.reserve("counter_evidence", 1)
        except CognitiveBudgetExhaustedError:
            return CounterEvidenceResult(status=CounterEvidenceStatus.BUDGET_EXHAUSTED, query=query)
    elif budget is not None:
        try:
            consume(budget, BudgetDimension.RETRIEVAL_CALLS, 1)
        except CognitiveBudgetExhaustedError:
            return CounterEvidenceResult(status=CounterEvidenceStatus.BUDGET_EXHAUSTED, query=query)

    try:
        results = await asyncio.wait_for(
            asyncio.to_thread(search_provider.search, query, 3), timeout=COUNTER_EVIDENCE_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        return CounterEvidenceResult(status=CounterEvidenceStatus.NOT_RUN, query=query)

    evidence: list[Evidence] = []
    for result in results:
        ev, _src = evidence_mod.evidence_from_search_result(result)
        evidence.append(ev)

    return CounterEvidenceResult(status=CounterEvidenceStatus.RAN, query=query, evidence=evidence)
