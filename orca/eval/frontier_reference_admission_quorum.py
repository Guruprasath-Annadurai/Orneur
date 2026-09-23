"""
Genesis Frontier Reference ADMISSION Quorum (Phase 21B.4.17).

This is deliberately a SEPARATE concern from
`orca.eval.frontier_stats.validate_frontier_reference_quorum`, which
validates quorum among references that were ACTUALLY EVALUATED on a
shared task set during a (not-yet-authorized) execution phase. This
module instead classifies quorum among references that are currently
ADMITTED to participate in future evaluation at all, based on the
registry's Phase 21B.4.17 admission/access-preflight fields -- a
pre-execution question, answered from registry data alone. Nothing
here evaluates a candidate, calls an API, or executes any model.

Per phase §15/§27: a frontier reference counts toward quorum only if
BOTH `reference_evaluation_admission_status == "ADMITTED"` AND at least
one access path is `QUALIFIED_FOR_FUTURE_EXECUTION` or
`PREFLIGHT_READY_PENDING_FRESH_ZERO_CASH_CHECK` (i.e.
`access_preflight_status` is one of those two values -- `UNQUALIFIED`,
`BLOCKED`, and `NOT_TESTED` do not count, even for an ADMITTED
reference). A reference must never count merely because a repository
exists, an API product exists, a model name is known, license is
unresolved, or access path is unverified.
"""
from __future__ import annotations

from dataclasses import dataclass

TARGET_REFERENCES = 6
MINIMUM_USABLE_REFERENCES = 4
MINIMUM_INDEPENDENT_ORGANIZATIONS = 3

_COUNTING_ACCESS_PREFLIGHT_STATUSES = frozenset(
    {"QUALIFIED_FOR_FUTURE_EXECUTION", "PREFLIGHT_READY_PENDING_FRESH_ZERO_CASH_CHECK"}
)

VALID_QUORUM_STATUSES = ("TARGET_READY", "MINIMUM_QUORUM_READY", "QUORUM_INCOMPLETE", "QUORUM_BLOCKED")


@dataclass(frozen=True)
class FrontierReferenceQuorumReport:
    admitted_reference_count: int
    access_preflight_ready_count: int
    quorum_counting_count: int
    quorum_counting_references: tuple[str, ...]
    independent_lineage_count: int
    independent_lineages: tuple[str, ...]
    quorum_status: str


def compute_admission_quorum(frontier_references: list[dict]) -> FrontierReferenceQuorumReport:
    """`frontier_references`: the registry's `frontier_references` list
    (each entry a dict with at least `reference_name`, `organization`,
    `reference_evaluation_admission_status`, `access_preflight_status`).

    Returns a report distinguishing three counts that must never be
    conflated (per phase §27):
      - admitted_reference_count: ADMITTED regardless of access path.
      - access_preflight_ready_count: access-path-ready regardless of
        admission status (a reference could theoretically have a ready
        access path while still license-REVIEW_REQUIRED).
      - quorum_counting_count: references satisfying BOTH conditions --
        this is the only count that determines quorum_status.
    """
    admitted = [r for r in frontier_references if r.get("reference_evaluation_admission_status") == "ADMITTED"]
    access_ready = [r for r in frontier_references if r.get("access_preflight_status") in _COUNTING_ACCESS_PREFLIGHT_STATUSES]
    quorum_counting = [
        r for r in frontier_references
        if r.get("reference_evaluation_admission_status") == "ADMITTED"
        and r.get("access_preflight_status") in _COUNTING_ACCESS_PREFLIGHT_STATUSES
    ]

    quorum_counting_names = tuple(sorted(r["reference_name"] for r in quorum_counting))
    lineages = tuple(sorted({r["organization"] for r in quorum_counting}))

    total_references = len(frontier_references)
    quorum_counting_count = len(quorum_counting)
    independent_lineage_count = len(lineages)

    if quorum_counting_count == 0:
        status = "QUORUM_BLOCKED"
    elif quorum_counting_count >= total_references == TARGET_REFERENCES and independent_lineage_count >= MINIMUM_INDEPENDENT_ORGANIZATIONS:
        # TARGET_READY requires ALL SIX references (per phase §27: "Do
        # not call TARGET_READY unless all six qualify") -- this branch
        # can only be reached if every registered reference both
        # admitted and access-ready.
        status = "TARGET_READY"
    elif quorum_counting_count >= MINIMUM_USABLE_REFERENCES and independent_lineage_count >= MINIMUM_INDEPENDENT_ORGANIZATIONS:
        status = "MINIMUM_QUORUM_READY"
    else:
        status = "QUORUM_INCOMPLETE"

    return FrontierReferenceQuorumReport(
        admitted_reference_count=len(admitted),
        access_preflight_ready_count=len(access_ready),
        quorum_counting_count=quorum_counting_count,
        quorum_counting_references=quorum_counting_names,
        independent_lineage_count=independent_lineage_count,
        independent_lineages=lineages,
        quorum_status=status,
    )
