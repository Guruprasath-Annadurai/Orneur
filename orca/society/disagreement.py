"""
Disagreement as a structured signal (Phase 7 spec §19-20). Never majority
vote -- disagreement TRIGGERS verification/escalation, it does not get
resolved by counting.
"""
from __future__ import annotations

from orca.deliberation.contracts import TwinResult
from orca.society.contracts import DisagreementSignal, DisagreementType


def compute_disagreement(twin_result: TwinResult) -> DisagreementSignal:
    """
    Derived entirely from TwinResult's own structured fields -- never from
    scanning claim/objection TEXT for sentiment, matching the same
    text-blind discipline Phase 6's Arbiter uses (spec §55: routing/
    disagreement inputs must be structured, not free-form model output
    read as authoritative).
    """
    types: list[DisagreementType] = []
    notes: list[str] = []

    if twin_result.disputed_claim_ids:
        types.append(DisagreementType.CLAIM_CONFLICT)
        notes.append(f"{len(twin_result.disputed_claim_ids)} claim(s) disputed by Falsifier")

    if twin_result.unsupported_assumption_ids:
        types.append(DisagreementType.ASSUMPTION_CONFLICT)
        notes.append(f"{len(twin_result.unsupported_assumption_ids)} assumption(s) flagged unsupported")

    if twin_result.counter_evidence_ids:
        types.append(DisagreementType.EVIDENCE_INTERPRETATION_CONFLICT)
        notes.append(f"{len(twin_result.counter_evidence_ids)} counter-evidence reference(s) raised")

    if not types:
        types.append(DisagreementType.NO_MEANINGFUL_DISAGREEMENT)
        notes.append("no disputed claims, unsupported assumptions, or counter-evidence found")

    if types == [DisagreementType.NO_MEANINGFUL_DISAGREEMENT]:
        severity = "NONE"
    elif twin_result.counter_evidence_ids and twin_result.disputed_claim_ids:
        severity = "HIGH"
    elif len(types) >= 2:
        severity = "MODERATE"
    else:
        severity = "LOW"

    return DisagreementSignal(
        types=types,
        disputed_claim_ids=list(twin_result.disputed_claim_ids),
        disputed_assumption_ids=list(twin_result.unsupported_assumption_ids),
        severity=severity,
        notes=notes,
    )
