"""
Phase 15.8 -- requirement-level aggregation, stale-evidence detection,
and verification-plan check ordering (spec sections 17, 21-22).

Aggregation truth table (non-vacuous by construction -- spec section
17's explicit warning against `all([]) == True`):

    zero criteria                      -> UNVERIFIED
    any required check FAIL            -> FAIL
    any required check UNVERIFIED/ERROR/CANCELLED/TIMED_OUT -> UNVERIFIED
    all required checks PASS/NOT_APPLICABLE -> PASS
"""
from __future__ import annotations

from dataclasses import dataclass

from orca.mission.verification import NON_PASSING_OUTCOMES, VerificationOutcome, VerificationRecord


class AggregationError(Exception):
    pass


def aggregate_outcomes(outcomes: tuple[VerificationOutcome, ...]) -> VerificationOutcome:
    """The single authoritative non-vacuous aggregation rule used
    everywhere in this package. An EMPTY tuple is UNVERIFIED, never a
    vacuous PASS."""
    if not outcomes:
        return VerificationOutcome.UNVERIFIED
    if VerificationOutcome.FAIL in outcomes:
        return VerificationOutcome.FAIL
    non_applicable = [o for o in outcomes if o is not VerificationOutcome.NOT_APPLICABLE]
    if not non_applicable:
        # every check was NOT_APPLICABLE -- vacuous, stays UNVERIFIED
        # rather than a hollow PASS with nothing actually observed.
        return VerificationOutcome.UNVERIFIED
    if any(o in NON_PASSING_OUTCOMES and o is not VerificationOutcome.FAIL for o in non_applicable):
        return VerificationOutcome.UNVERIFIED
    return VerificationOutcome.PASS


def aggregate_requirement(records: tuple[VerificationRecord, ...]) -> VerificationOutcome:
    """Aggregates the LATEST record per (criterion_id or category) --
    older records remain in history but do not count twice. Records
    with `criterion_id is None` are grouped by `category` instead."""
    if not records:
        return VerificationOutcome.UNVERIFIED
    latest_by_key: dict[str, VerificationRecord] = {}
    for r in records:
        key = r.criterion_id or f"category:{r.category}"
        existing = latest_by_key.get(key)
        if existing is None or r.started_at >= existing.started_at:
            latest_by_key[key] = r
    return aggregate_outcomes(tuple(r.outcome for r in latest_by_key.values()))


# ── Stale evidence detection (spec section 21) ──────────────────────

def is_evidence_stale(record: VerificationRecord, *, current_revision: str) -> bool:
    """A record whose `revision` does not match the current revision
    is stale -- it must not silently count as proof for the new
    revision."""
    return record.revision != current_revision


def filter_current_revision(
    records: tuple[VerificationRecord, ...], *, current_revision: str,
) -> tuple[VerificationRecord, ...]:
    """Records for a DIFFERENT revision are excluded from aggregation
    entirely -- they remain visible in full history via
    verifications_for_requirement(), just not counted as current
    proof."""
    return tuple(r for r in records if not is_evidence_stale(r, current_revision=current_revision))


# ── Verification plan check ordering (spec section 22) ──────────────

@dataclass(frozen=True)
class CheckOrderingEdge:
    before: str  # category name
    after: str   # category name


class CheckOrderingError(Exception):
    pass


def validate_check_ordering(edges: tuple[CheckOrderingEdge, ...]) -> None:
    """Rejects a cycle in the BEFORE/AFTER ordering graph. This is
    ONLY dependency metadata for verification categories -- it does
    not implement a workflow engine (the mission engine already owns
    mission workflow, per the explicit instruction not to overbuild
    one here)."""
    graph: dict[str, list[str]] = {}
    for e in edges:
        graph.setdefault(e.before, []).append(e.after)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {}

    def _visit(node: str) -> None:
        color[node] = GRAY
        for neighbor in graph.get(node, []):
            state = color.get(neighbor, WHITE)
            if state == GRAY:
                raise CheckOrderingError(f"cycle detected in verification check ordering: ...{node} -> {neighbor}...")
            if state == WHITE:
                _visit(neighbor)
        color[node] = BLACK

    for node in list(graph.keys()):
        if color.get(node, WHITE) == WHITE:
            _visit(node)
