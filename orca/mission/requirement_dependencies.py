"""
Phase 15.7 -- requirement dependencies and conflict detection
(spec sections 8-9).

Dependencies are a plain directed-edge registry over
`orca.mission.requirements` IDs (both endpoints must already be
registered requirements -- no dangling edges). Conflict detection is
a deterministic, structurally-obvious keyword-pair heuristic -- it
does NOT attempt general contradiction reasoning, and it never
invents a resolution: a detected conflict is only ever represented
and surfaced, per the explicit instruction "require clarification, an
owner decision, or explicit design resolution."
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from orca.mission import requirements as requirements_module


class DependencyKind(str, Enum):
    DEPENDS_ON = "DEPENDS_ON"
    BLOCKS = "BLOCKS"
    DERIVED_FROM = "DERIVED_FROM"
    CONFLICTS_WITH = "CONFLICTS_WITH"


class DependencyError(Exception):
    pass


@dataclass(frozen=True)
class Dependency:
    from_id: str
    kind: DependencyKind
    to_id: str


_EDGES: list[Dependency] = []


def reset_registry_for_tests() -> None:
    _EDGES.clear()


def _require_registered(req_id: str) -> None:
    try:
        requirements_module.get(req_id)
    except requirements_module.RequirementError:
        raise DependencyError(f"{req_id!r} is not a registered requirement.") from None


def add_dependency(from_id: str, kind: DependencyKind, to_id: str) -> Dependency:
    if from_id == to_id:
        raise DependencyError(f"{from_id!r} cannot depend on itself.")
    _require_registered(from_id)
    _require_registered(to_id)
    edge = Dependency(from_id=from_id, kind=kind, to_id=to_id)
    if edge in _EDGES:
        return edge  # idempotent re-add, not an error
    if kind is DependencyKind.DEPENDS_ON:
        _assert_no_cycle(from_id, to_id)
    _EDGES.append(edge)
    return edge


def dependencies_of(req_id: str, kind: DependencyKind | None = None) -> tuple[Dependency, ...]:
    return tuple(e for e in _EDGES if e.from_id == req_id and (kind is None or e.kind == kind))


def _assert_no_cycle(from_id: str, to_id: str) -> None:
    """Would adding from_id -DEPENDS_ON-> to_id create a cycle in the
    DEPENDS_ON subgraph? Simple DFS from to_id looking for a path back
    to from_id."""
    stack = [to_id]
    visited: set[str] = set()
    while stack:
        node = stack.pop()
        if node == from_id:
            raise DependencyError(
                f"adding {from_id} DEPENDS_ON {to_id} would create a dependency cycle."
            )
        if node in visited:
            continue
        visited.add(node)
        for e in _EDGES:
            if e.from_id == node and e.kind is DependencyKind.DEPENDS_ON:
                stack.append(e.to_id)


def unmet_blocking_dependencies(req_id: str) -> tuple[str, ...]:
    """DEPENDS_ON targets that are not yet VERIFIED -- these remain
    visible to later verification (spec section 8), never hidden."""
    unmet = []
    for e in dependencies_of(req_id, DependencyKind.DEPENDS_ON):
        target = requirements_module.get(e.to_id)
        if target.status is not requirements_module.RequirementStatus.VERIFIED:
            unmet.append(e.to_id)
    return tuple(unmet)


# ── Conflict detection (spec section 9) ─────────────────────────────

@dataclass(frozen=True)
class Conflict:
    requirement_a: str
    requirement_b: str
    reason: str


#: Deterministic, structurally-obvious contradiction pairs. Each pair
#: is (phrase that must appear in one statement, phrase that must
#: appear in the other) -- both case-insensitive substring checks.
#: This is intentionally narrow: it catches the exact "all data must
#: remain local" vs "upload all data to third-party service" class of
#: example from the spec, not general semantic contradiction.
_CONTRADICTION_PAIRS: tuple[tuple[str, str, str], ...] = (
    ("must remain local", "upload", "data locality vs external upload"),
    ("must remain local", "third-party", "data locality vs third-party transfer"),
    ("no third-party", "third-party service", "no-third-party constraint vs third-party integration"),
    ("offline only", "cloud", "offline-only constraint vs cloud dependency"),
)


def detect_conflicts(req_ids: tuple[str, ...]) -> tuple[Conflict, ...]:
    """Deterministic, order-independent: checks every pair of the
    given requirement IDs' `statement` text against the known
    contradiction-phrase table. Never resolves a conflict -- only
    reports it."""
    conflicts: list[Conflict] = []
    reqs = [requirements_module.get(r) for r in req_ids]
    for i, req_a in enumerate(reqs):
        for req_b in reqs[i + 1:]:
            stmt_a = req_a.statement.lower()
            stmt_b = req_b.statement.lower()
            for phrase_a, phrase_b, reason in _CONTRADICTION_PAIRS:
                a_has_first = phrase_a in stmt_a
                b_has_second = phrase_b in stmt_b
                a_has_second = phrase_b in stmt_a
                b_has_first = phrase_a in stmt_b
                if (a_has_first and b_has_second) or (b_has_first and a_has_second):
                    conflicts.append(Conflict(requirement_a=req_a.id, requirement_b=req_b.id, reason=reason))
    return tuple(conflicts)
