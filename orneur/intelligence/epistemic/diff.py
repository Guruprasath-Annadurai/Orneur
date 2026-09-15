"""
Deterministic diff between two EpistemicOverlays. Representation/audit
only -- Phase 18 makes no enforcement decisions here; Phase 19 will
consume this. Doctrine: epistemic state is time/context-relative and is
NOT monotonically increasing -- new evidence may reduce certainty (e.g.
KNOWN -> DISPUTED is a valid, expected transition, not a bug).
"""
from __future__ import annotations

from dataclasses import dataclass

from orneur.intelligence.epistemic.enums import EpistemicPolarity, EpistemicReasonCode, EpistemicState
from orneur.intelligence.epistemic.models import EpistemicOverlay


@dataclass(frozen=True)
class EpistemicTransition:
    atom_id: str
    previous_state: EpistemicState | None
    new_state: EpistemicState | None
    previous_polarity: EpistemicPolarity | None
    new_polarity: EpistemicPolarity | None
    added_reason_codes: tuple[EpistemicReasonCode, ...] = ()
    removed_reason_codes: tuple[EpistemicReasonCode, ...] = ()
    added_evidence_refs: tuple[str, ...] = ()
    removed_evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class EpistemicDiff:
    from_overlay_id: str
    to_overlay_id: str
    transitions: tuple[EpistemicTransition, ...] = ()


def diff(a: EpistemicOverlay, b: EpistemicOverlay) -> EpistemicDiff:
    by_id_a = {assessment.atom_id: assessment for assessment in a.assessments}
    by_id_b = {assessment.atom_id: assessment for assessment in b.assessments}
    all_atom_ids = sorted(set(by_id_a) | set(by_id_b))

    transitions = []
    for atom_id in all_atom_ids:
        before = by_id_a.get(atom_id)
        after = by_id_b.get(atom_id)
        if before is not None and after is not None and before == after:
            continue

        before_evidence = set(before.direct_support_evidence_refs + before.direct_refutation_evidence_refs) if before else set()
        after_evidence = set(after.direct_support_evidence_refs + after.direct_refutation_evidence_refs) if after else set()
        before_reasons = set(before.reason_codes) if before else set()
        after_reasons = set(after.reason_codes) if after else set()

        transitions.append(
            EpistemicTransition(
                atom_id=atom_id,
                previous_state=before.state if before else None,
                new_state=after.state if after else None,
                previous_polarity=before.polarity if before else None,
                new_polarity=after.polarity if after else None,
                added_reason_codes=tuple(sorted(after_reasons - before_reasons, key=lambda r: r.value)),
                removed_reason_codes=tuple(sorted(before_reasons - after_reasons, key=lambda r: r.value)),
                added_evidence_refs=tuple(sorted(after_evidence - before_evidence)),
                removed_evidence_refs=tuple(sorted(before_evidence - after_evidence)),
            )
        )

    return EpistemicDiff(
        from_overlay_id=a.overlay_id,
        to_overlay_id=b.overlay_id,
        transitions=tuple(transitions),
    )
