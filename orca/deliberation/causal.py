"""
Causal Graph foundation (Phase 6 spec §23-24). Bounded, deterministic
classification -- a causal claim requires STRONGER support than a
correlation claim, and that upgrade is never inferred from prose alone.
Model output can SUPPLY the signals (temporal precedence, a mechanism
explanation, a controlled comparison) as explicit structured fields, but
this module -- not free text -- decides what relationship TYPE those
signals justify.
"""
from __future__ import annotations

from orca.deliberation.contracts import CausalRelation, CausalRelationType

MAX_RELATIONS_PER_GRAPH = 20


def assess_causal_relation(
    cause: str, effect: str, evidence_ids: list[str], *,
    temporal_precedence: bool = False, mechanism_explained: bool = False, controlled_comparison: bool = False,
    prevents: bool = False,
) -> CausalRelation:
    """
    Classification rule (spec §24):
      - no evidence at all                              -> UNKNOWN
      - a controlled comparison, OR (temporal precedence
        AND a mechanism explanation)                     -> CAUSES
      - temporal precedence OR a mechanism explanation
        alone (one signal, not both)                     -> CONTRIBUTES_TO
      - evidence exists but none of the above signals     -> CORRELATES_WITH
        (association only -- exactly the case spec §24
        says must never be silently upgraded to causation)
    `prevents=True` maps a would-be CAUSES/CONTRIBUTES_TO relationship to
    PREVENTS instead, using the same evidentiary bar.
    """
    if not evidence_ids:
        rel_type = CausalRelationType.UNKNOWN
        confidence = None
    elif controlled_comparison or (temporal_precedence and mechanism_explained):
        rel_type = CausalRelationType.PREVENTS if prevents else CausalRelationType.CAUSES
        confidence = 0.8
    elif temporal_precedence or mechanism_explained:
        rel_type = CausalRelationType.CONTRIBUTES_TO
        confidence = 0.5
    else:
        rel_type = CausalRelationType.CORRELATES_WITH
        confidence = 0.3

    return CausalRelation(
        cause=cause, effect=effect, relationship_type=rel_type,
        evidence_ids=list(evidence_ids), confidence=confidence,
    )


class CausalGraph:
    """Bounded container -- never an unrestricted growing graph (spec
    §23, matching the same "bounded everything" discipline already
    established by orca/truth/planner.py and orca/memory/reflex.py)."""

    def __init__(self):
        self._relations: list[CausalRelation] = []

    def add(self, relation: CausalRelation) -> bool:
        if len(self._relations) >= MAX_RELATIONS_PER_GRAPH:
            return False
        self._relations.append(relation)
        return True

    @property
    def relations(self) -> list[CausalRelation]:
        return list(self._relations)

    def relations_for(self, cause: str | None = None, effect: str | None = None) -> list[CausalRelation]:
        return [
            r for r in self._relations
            if (cause is None or r.cause == cause) and (effect is None or r.effect == effect)
        ]

    def correlation_only(self) -> list[CausalRelation]:
        """The set of relations still resting on association evidence
        only -- exactly what spec §24 wants distinguishable from real
        causal claims."""
        return [r for r in self._relations if r.relationship_type == CausalRelationType.CORRELATES_WITH]
