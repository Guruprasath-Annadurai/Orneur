"""
Hypothesis Space (Phase 6 spec §7-9). Explicit lifecycle transitions --
never a silent delete. A FALSIFIED hypothesis stays in the
HypothesisSet, visible for audit, forever.
"""
from __future__ import annotations

from orca.deliberation.contracts import EvidenceNeed, Hypothesis, HypothesisSet, HypothesisStatus, _now_iso


def record_supporting_evidence(hypothesis: Hypothesis, evidence_id: str) -> None:
    if evidence_id not in hypothesis.supporting_evidence_ids:
        hypothesis.supporting_evidence_ids.append(evidence_id)
    _recompute_status(hypothesis)


def record_contradicting_evidence(hypothesis: Hypothesis, evidence_id: str) -> None:
    if evidence_id not in hypothesis.contradicting_evidence_ids:
        hypothesis.contradicting_evidence_ids.append(evidence_id)
    _recompute_status(hypothesis)


def falsify(hypothesis: Hypothesis, evidence_id: str | None = None) -> None:
    """Explicit, decisive -- called by the Falsifier when it judges the
    hypothesis genuinely broken, not merely weakened by one piece of
    conflicting evidence. FALSIFIED is terminal: _recompute_status()
    never auto-reverts it even if later evidence supports it again --
    that would require a NEW hypothesis, preserving the falsification
    record (spec §7: never silently delete a losing hypothesis)."""
    if evidence_id:
        record_contradicting_evidence(hypothesis, evidence_id)
    hypothesis.status = HypothesisStatus.FALSIFIED
    hypothesis.updated_at = _now_iso()


def _recompute_status(hypothesis: Hypothesis) -> None:
    if hypothesis.status == HypothesisStatus.FALSIFIED:
        return  # terminal
    support_n = len(hypothesis.supporting_evidence_ids)
    contra_n = len(hypothesis.contradicting_evidence_ids)
    if contra_n > 0 and contra_n > support_n:
        hypothesis.status = HypothesisStatus.WEAKENED
    elif support_n > 0 and contra_n == 0:
        hypothesis.status = HypothesisStatus.SUPPORTED
    else:
        hypothesis.status = HypothesisStatus.ACTIVE
    hypothesis.updated_at = _now_iso()


def mark_unresolved(hypothesis: Hypothesis) -> None:
    """Explicit terminal state for a hypothesis the process ran out of
    budget/rounds to further distinguish -- distinct from ACTIVE (still
    being investigated) and distinct from FALSIFIED (positively broken)."""
    hypothesis.status = HypothesisStatus.UNRESOLVED
    hypothesis.updated_at = _now_iso()


def all_resolved(hypothesis_set: HypothesisSet) -> bool:
    """A stop condition (spec §31): true once no hypothesis is still
    ACTIVE/WEAKENED (i.e. every one has reached SUPPORTED, FALSIFIED, or
    UNRESOLVED)."""
    return not any(h.status in (HypothesisStatus.ACTIVE, HypothesisStatus.WEAKENED) for h in hypothesis_set.hypotheses)


def distinguishing_evidence_need(hypothesis_a: Hypothesis, hypothesis_b: Hypothesis) -> EvidenceNeed:
    """Spec §9's core question, structured: "What observation would
    distinguish these hypotheses?" -- a template, not free prose; Truth
    Fabric/tools consume `question` directly."""
    return EvidenceNeed(
        question=(
            f"What observation would confirm '{hypothesis_a.statement}' "
            f"while ruling out '{hypothesis_b.statement}' (or vice versa)?"
        ),
        distinguishes_hypothesis_ids=[hypothesis_a.hypothesis_id, hypothesis_b.hypothesis_id],
    )
