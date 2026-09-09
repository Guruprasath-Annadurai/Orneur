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


def _latest_by_key(records: tuple[VerificationRecord, ...]) -> dict[str, VerificationRecord]:
    """Groups records by (criterion_id or category) and keeps only the
    LATEST record per key -- older records remain in history but do
    not count twice. Records with `criterion_id is None` are grouped
    by `category` instead (a legitimate pre-existing pattern for
    requirement-level checks that were never modeled as an
    `AcceptanceCriterion` object -- Phase 15.9.3 closure item 3).
    Shared by `aggregate_requirement()` and
    `evaluate_requirement_completion()` so both use the exact same
    per-key latest-wins rule."""
    latest_by_key: dict[str, VerificationRecord] = {}
    for r in records:
        key = r.criterion_id or f"category:{r.category}"
        existing = latest_by_key.get(key)
        if existing is None or r.started_at >= existing.started_at:
            latest_by_key[key] = r
    return latest_by_key


def aggregate_requirement(records: tuple[VerificationRecord, ...]) -> VerificationOutcome:
    """Aggregates the LATEST record per (criterion_id or category) --
    older records remain in history but do not count twice. Records
    with `criterion_id is None` are grouped by `category` instead.

    This is the original Phase 15.8 aggregation rule: it only ever
    knows about whatever keys are PRESENT in `records` -- it cannot by
    itself detect that a caller expected additional criteria that have
    no record at all (that is exactly the gap
    `evaluate_requirement_completion()` below closes for the mission/
    Court completion path; this function's own contract and existing
    callers/tests are otherwise unchanged, Phase 15.9.3 closure item
    2)."""
    if not records:
        return VerificationOutcome.UNVERIFIED
    return aggregate_outcomes(tuple(r.outcome for r in _latest_by_key(records).values()))


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


def is_evidence_for_other_mission(record: VerificationRecord, *, mission_id: str | None) -> bool:
    """A record whose `mission_id` does not match the expected
    mission is for a DIFFERENT mission -- it must never silently
    count as proof for this one, mirroring `is_evidence_stale()`'s
    revision-binding discipline (Phase 15.9.1 closure item 2/5)."""
    if mission_id is None:
        return False  # no mission scoping requested -- caller's choice, not this function's to enforce
    return record.mission_id != mission_id


def filter_current_context(
    records: tuple[VerificationRecord, ...], *, current_revision: str, mission_id: str | None = None,
) -> tuple[VerificationRecord, ...]:
    """`filter_current_revision()` PLUS mission binding: a record from
    mission B must never count as proof for mission A, exactly as a
    record from revision A must never count as proof for revision B.
    This is the single function `orca.mission.cognitive_court
    .arbiter_decide()` and `orca.mission.mission_verification_gate`
    both use, so the binding rule lives in exactly one place."""
    current_revision_records = filter_current_revision(records, current_revision=current_revision)
    if mission_id is None:
        return current_revision_records
    return tuple(r for r in current_revision_records if not is_evidence_for_other_mission(r, mission_id=mission_id))


def is_evidence_for_other_requirement(record: VerificationRecord, *, requirement_id: str | None) -> bool:
    """A record whose `requirement_id` does not match the expected
    requirement must never silently count as proof for this one --
    mirroring `is_evidence_stale()`/`is_evidence_for_other_mission()`'s
    binding discipline. This closes the specific Phase 15.9.3 audit
    gap: a caller placing a record under `records_by_requirement["REQ-
    B"]` whose OWN `record.requirement_id` is actually `"REQ-A"` must
    not count -- the dictionary key a record happens to be filed under
    is never itself authority for the record's identity."""
    if requirement_id is None:
        return False  # no requirement scoping requested -- caller's choice, not this function's to enforce
    return record.requirement_id != requirement_id


def filter_current_requirement_context(
    records: tuple[VerificationRecord, ...], *, current_revision: str, requirement_id: str | None,
    mission_id: str | None = None,
) -> tuple[VerificationRecord, ...]:
    """`filter_current_context()` PLUS requirement-id binding: a
    record whose own `requirement_id` does not genuinely match
    `requirement_id` must never count as proof for it, regardless of
    which dictionary key a caller filed it under (Phase 15.9.3 closure
    item 1). This is the single function `evaluate_requirement_
    completion()` below uses, which `orca.mission.cognitive_court
    .arbiter_decide()` and `orca.mission.mission_verification_gate`
    both call in turn -- the requirement-identity binding rule lives
    in exactly one place, exactly as the mission/revision binding
    rules already do."""
    scoped = filter_current_context(records, current_revision=current_revision, mission_id=mission_id)
    if requirement_id is None:
        return scoped
    return tuple(r for r in scoped if not is_evidence_for_other_requirement(r, requirement_id=requirement_id))


# ── Criterion-complete requirement evaluation (spec section 7/16-18) ─

def expected_keys_for_requirement(requirement_id: str) -> frozenset[str] | None:
    """Derives the authoritative set of required aggregation keys for
    a requirement from the Phase 15.7 `AcceptanceCriterion` registry's
    existing `criteria_for_requirement()` -- no new criteria registry
    is invented here (Phase 15.9.3 closure item 2). Returns `None`
    (deliberately NOT an empty set -- an empty set would mean "zero
    keys are required," which is a vacuous-pass hazard) when the
    registry has ZERO criteria registered for this requirement, so
    callers can distinguish "no criterion scope is known" from
    "criterion scope is known to be empty" and fall back to the
    legacy whatever-exists-in-records aggregation for genuine
    requirement-level checks that were never modeled as
    `AcceptanceCriterion` objects (closure item 3)."""
    from orca.mission.acceptance_criteria import criteria_for_requirement
    criteria = criteria_for_requirement(requirement_id)
    if not criteria:
        return None
    return frozenset(c.criterion_id for c in criteria)


def evaluate_requirement_completion(
    records: tuple[VerificationRecord, ...], *, requirement_id: str, current_revision: str,
    mission_id: str | None = None, required_criterion_ids: frozenset[str] | None = None,
) -> tuple[VerificationOutcome, tuple[VerificationRecord, ...]]:
    """GENERIC/LEGACY requirement-completion aggregation (Phase 15.9.3
    closure item 8). As of Phase 15.9.4, this function is NO LONGER
    used by `arbiter_decide()` or `orca.mission.mission_verification_
    gate` -- an independent audit found its Phase-15.7-registry/
    whatever-exists fallback to be fail-OPEN on the Court/
    COMPLETED_VERIFIED path: a separately-started process that never
    repopulates the in-process `AcceptanceCriterion` registry would
    silently accept a weaker verification scope than intended. The
    mission-critical path now calls `evaluate_requirement_completion_
    for_mission()` below instead, which requires an explicit, already-
    resolved `RequiredVerificationScope` and never itself queries that
    registry. THIS function remains available, unchanged, for generic/
    non-mission-critical callers that are not capable of producing
    ACCEPT or COMPLETED_VERIFIED -- do not wire it back into either of
    those paths. Combines every identity dimension that must hold
    before a PASS may count:

      MISSION    -- via `filter_current_context()`'s mission binding.
      REVISION   -- via `filter_current_context()`'s revision binding.
      REQUIREMENT -- via `filter_current_requirement_context()`'s new
                     requirement-id binding (closure item 1): a record
                     is never trusted merely because a caller filed it
                     under `records_by_requirement[requirement_id]`.
      CRITERION / required verification scope -- closure item 2: when
                     `required_criterion_ids` is supplied explicitly,
                     or (if not) the Phase 15.7 `AcceptanceCriterion`
                     registry has one or more criteria registered for
                     `requirement_id`, EVERY one of those keys must
                     have a current-context PASS -- a required
                     criterion with zero matching records is treated
                     as UNVERIFIED for that key, never silently
                     omitted from the aggregate. A key present in the
                     records but NOT in the required set (e.g. an
                     unrelated criterion C3) is never consulted and
                     can never substitute for a missing required key.

    When NEITHER an explicit `required_criterion_ids` override NOR any
    registered `AcceptanceCriterion` exists for `requirement_id`, this
    falls back to the original Phase 15.8 `aggregate_requirement()`
    behavior -- whatever keys happen to be present in the scoped
    records -- preserving backward compatibility for every existing
    generic caller/test that never registered a criterion (a
    legitimate requirement-level-check pattern, closure item 3), while
    giving the mission/Court completion path a way to supply or derive
    a real explicit scope and fail closed against missing criteria.

    Returns `(aggregated_outcome, records_that_actually_produced_a_
    PASS_contribution)` -- the second element is exactly the set of
    real records a caller (e.g. `arbiter_decide()`) should fold into
    `CourtDecision.verification_refs`; it is empty whenever the
    aggregated outcome is not PASS."""
    scoped = filter_current_requirement_context(
        records, current_revision=current_revision, requirement_id=requirement_id, mission_id=mission_id,
    )

    required_keys = required_criterion_ids
    if required_keys is None:
        required_keys = expected_keys_for_requirement(requirement_id)

    if required_keys is None:
        outcome = aggregate_requirement(scoped)
        if outcome is not VerificationOutcome.PASS:
            return outcome, ()
        latest = _latest_by_key(scoped)
        contributing = tuple(r for r in latest.values() if r.outcome is VerificationOutcome.PASS)
        return outcome, contributing

    latest = _latest_by_key(scoped)
    outcomes: list[VerificationOutcome] = []
    contributing = []
    for key in required_keys:
        record = latest.get(key)
        if record is None:
            outcomes.append(VerificationOutcome.UNVERIFIED)  # missing required criterion != PASS
            continue
        outcomes.append(record.outcome)
        if record.outcome is VerificationOutcome.PASS:
            contributing.append(record)
    outcome = aggregate_outcomes(tuple(outcomes))
    if outcome is not VerificationOutcome.PASS:
        return outcome, ()
    return outcome, tuple(contributing)


# ── Mission-critical authoritative scope (Phase 15.9.4 closure) ─────

class ScopeError(Exception):
    pass


@dataclass(frozen=True)
class RequiredVerificationScope:
    """The EXPLICIT, authoritative statement of which verification
    keys are required for one requirement on the Court/
    COMPLETED_VERIFIED mission-critical path (Phase 15.9.4 closure).

    `evaluate_requirement_completion()` (above) is a GENERIC/LEGACY
    helper: when it has no explicit override, it falls back to either
    the Phase 15.7 `AcceptanceCriterion` in-process registry or, if
    that registry has nothing registered either, to "whatever keys
    happen to be present in the records" -- a fallback that is
    acceptable for generic, non-mission-critical callers, but was
    found (Phase 15.9.4 audit) to be a fail-OPEN hole on the Court/
    completion path: a separately-started process that never
    repopulates the in-process registry would silently accept a
    weaker verification scope than the one originally intended, and
    the decision would depend on accidental in-process state rather
    than on anything durable or explicitly supplied.

    `RequiredVerificationScope` closes that hole by being the ONLY
    thing the mission-critical path (`evaluate_requirement_completion_
    for_mission()` below, and therefore `arbiter_decide()` and
    `orca.mission.mission_verification_gate`) will accept as
    authority for what is required -- it never itself queries the
    Phase 15.7 registry. A caller MAY use that registry (via
    `expected_keys_for_requirement()`) as a convenient way to BUILD a
    `RequiredVerificationScope` before calling, but the mission-
    critical function itself takes only this explicit, already-
    resolved object -- so a process restart that clears the in-memory
    registry cannot silently change the ACCEPT/COMPLETED_VERIFIED
    decision for evidence that was already gathered.

    Expresses BOTH pre-existing verification-key forms (closure item
    3) -- `criterion_ids` for criterion-backed verification
    (`record.criterion_id` set to a real Phase 15.7 `AcceptanceCriterion
    .criterion_id`) and `requirement_level_categories` for the
    equally-legitimate pre-existing pattern of requirement-level
    checks with `record.criterion_id is None`, grouped by
    `record.category` instead -- so no historical requirement-level
    check needs to be forced into a fake `AcceptanceCriterion` object
    just to be expressible here.

    The scope itself must be non-empty: at least one of `criterion_ids`
    / `requirement_level_categories` must be supplied, or construction
    raises `ScopeError` -- an EMPTY scope can never be treated as "no
    verification is required," which would be exactly the vacuous-pass
    hazard this whole closure lineage (Phase 15.9.2 item 1) exists to
    prevent."""
    criterion_ids: frozenset[str] = frozenset()
    requirement_level_categories: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.criterion_ids and not self.requirement_level_categories:
            raise ScopeError(
                "RequiredVerificationScope must declare at least one criterion_id or "
                "requirement_level_category -- an empty scope can never authorize "
                "ACCEPT/COMPLETED_VERIFIED (Phase 15.9.4 closure)."
            )

    @property
    def keys(self) -> frozenset[str]:
        """The exact internal aggregation-key convention `_latest_by_
        key()` already uses (a bare criterion_id, or `category:<name>`
        for a requirement-level check) -- exposed here so callers never
        need to construct that magic-string convention themselves."""
        return self.criterion_ids | frozenset(f"category:{c}" for c in self.requirement_level_categories)


def evaluate_requirement_completion_for_mission(
    records: tuple[VerificationRecord, ...], *, requirement_id: str, current_revision: str,
    mission_id: str, required_scope: RequiredVerificationScope,
) -> tuple[VerificationOutcome, tuple[VerificationRecord, ...]]:
    """THE single authoritative aggregation function for the Court/
    `COMPLETED_VERIFIED` mission-critical path (Phase 15.9.4 closure
    item 9's "central truth rule" -- `arbiter_decide()` and
    `orca.mission.mission_verification_gate` both call this, and any
    future Production Proof aggregation should too, rather than
    inventing another truth rule). Requires, and holds, exactly the
    four identity/scope dimensions that must all agree before a PASS
    counts:

      MISSION    -- via `filter_current_context()`'s mission binding.
      REVISION   -- via `filter_current_context()`'s revision binding.
      REQUIREMENT -- via `filter_current_requirement_context()`'s
                     requirement-id binding (Phase 15.9.3 closure item
                     1) -- a record is never trusted merely because a
                     caller filed it under a matching dict key.
      EXPECTED VERIFICATION SCOPE -- `required_scope`, an EXPLICIT,
                     already-resolved `RequiredVerificationScope` the
                     caller must supply -- this function never
                     consults the Phase 15.7 in-process registry
                     itself, so its result cannot change merely
                     because that registry was or wasn't populated in
                     this process (Phase 15.9.4 closure item 4's
                     fail-closed guarantee).

    `mission_id` is required (non-optional, unlike the generic
    `evaluate_requirement_completion()`) because there is no
    legitimate unscoped call on this path -- the Court/completion
    callers already validate this themselves (Phase 15.9.2 closure),
    but this function enforces it independently too, defense in
    depth.

    Returns `(aggregated_outcome, records_that_actually_produced_a_
    PASS_contribution)`, exactly as `evaluate_requirement_completion()`
    does; `contributing` is always empty when the outcome is not
    PASS."""
    if not mission_id:
        raise ScopeError(
            "evaluate_requirement_completion_for_mission() requires a non-empty "
            "mission_id -- there is no legitimate unscoped call on the mission-"
            "critical path (Phase 15.9.4 closure)."
        )
    scoped = filter_current_requirement_context(
        records, current_revision=current_revision, requirement_id=requirement_id, mission_id=mission_id,
    )
    latest = _latest_by_key(scoped)
    outcomes: list[VerificationOutcome] = []
    contributing: list[VerificationRecord] = []
    for key in required_scope.keys:
        record = latest.get(key)
        if record is None:
            outcomes.append(VerificationOutcome.UNVERIFIED)  # missing required scope key != PASS
            continue
        outcomes.append(record.outcome)
        if record.outcome is VerificationOutcome.PASS:
            contributing.append(record)
    outcome = aggregate_outcomes(tuple(outcomes))
    if outcome is not VerificationOutcome.PASS:
        return outcome, ()
    return outcome, tuple(contributing)


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
