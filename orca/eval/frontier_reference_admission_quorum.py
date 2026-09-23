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

Phase 21B.4.17.2 §9 clarification: `compute_admission_quorum()`'s
`access_preflight_status` field (and therefore its `quorum_status`
result) represents readiness for the FULL Genesis frontier protocol,
which ultimately includes the sealed PRIVATE HOLDOUT -- not merely
public/internal evaluation. A reference whose only practical access
path cannot yet safely receive confidential holdout material (e.g. a
provider whose terms permit training on submitted API input, with no
confirmed opt-out or enterprise no-training arrangement) must NOT be
counted as full-protocol-ready even if it is perfectly usable for
public/internal evaluation. `compute_public_eval_ready_count()` below
exposes that narrower, informational count separately -- only the main
report's `quorum_status` may ever satisfy `MINIMUM_QUORUM_READY` for
the locked Genesis selection process.
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


class AccessReadinessError(AssertionError):
    """Raised by `validate_full_protocol_access_readiness` when a claimed
    ready access_preflight_status is not actually supported by the
    underlying non-financial evidence."""


def validate_full_protocol_access_readiness(
    access_preflight_status: str,
    *,
    reference_evaluation_admission_status: str,
    license_or_terms_status: str,
    evidence_retention_status: str,
    automated_evaluation_status: str,
    private_holdout_status: str,
    access_path_identified: bool,
    model_identity_attributable: bool,
) -> None:
    """Phase 21B.4.17.2 §8: a REAL fail-closed gate, not merely an enum
    membership check. If `access_preflight_status` claims a counting
    status (`QUALIFIED_FOR_FUTURE_EXECUTION` or
    `PREFLIGHT_READY_PENDING_FRESH_ZERO_CASH_CHECK`), every one of the
    following non-financial preconditions must actually hold, or this
    raises `AccessReadinessError` naming the first failing precondition:
      - reference evaluation admission == ADMITTED
      - governing terms == CLEAR
      - evidence retention == PERMITTED
      - automated evaluation == CLEAR
      - private-holdout compatibility == PERMITTED (required for
        FULL-PROTOCOL quorum counting specifically -- a reference that
        is merely public-eval-ready must not pass this check)
      - an identified access path is real
      - model identity is sufficiently attributable

    A status outside the counting set is not checked -- there is
    nothing to validate when readiness isn't being claimed."""
    if access_preflight_status not in _COUNTING_ACCESS_PREFLIGHT_STATUSES:
        return
    if reference_evaluation_admission_status != "ADMITTED":
        raise AccessReadinessError(
            f"access_preflight_status={access_preflight_status!r} claimed but "
            f"reference_evaluation_admission_status={reference_evaluation_admission_status!r} != ADMITTED"
        )
    if license_or_terms_status != "CLEAR":
        raise AccessReadinessError(
            f"access_preflight_status={access_preflight_status!r} claimed but "
            f"license_or_terms_status={license_or_terms_status!r} != CLEAR"
        )
    if evidence_retention_status != "PERMITTED":
        raise AccessReadinessError(
            f"access_preflight_status={access_preflight_status!r} claimed but "
            f"evidence_retention_status={evidence_retention_status!r} != PERMITTED"
        )
    if automated_evaluation_status != "CLEAR":
        raise AccessReadinessError(
            f"access_preflight_status={access_preflight_status!r} claimed but "
            f"automated_evaluation_status={automated_evaluation_status!r} != CLEAR"
        )
    if private_holdout_status != "PERMITTED":
        raise AccessReadinessError(
            f"access_preflight_status={access_preflight_status!r} claimed FULL-PROTOCOL readiness but "
            f"private_holdout_status={private_holdout_status!r} != PERMITTED"
        )
    if not access_path_identified:
        raise AccessReadinessError(f"access_preflight_status={access_preflight_status!r} claimed but no identified access path")
    if not model_identity_attributable:
        raise AccessReadinessError(f"access_preflight_status={access_preflight_status!r} claimed but model identity is not sufficiently attributable")


def compute_public_eval_ready_count(frontier_references: list[dict]) -> int:
    """Informational-only count (§9): references that are ADMITTED and
    whose `public_eval_access_preflight_status` (falling back to
    `access_preflight_status` when a reference has no separate
    public-eval field) is a counting status. This count is NEVER used
    to satisfy `MINIMUM_QUORUM_READY` -- it exists only so a reference
    that is usable for public/internal evaluation but not yet safe for
    the sealed private holdout is not silently invisible in reporting."""
    count = 0
    for r in frontier_references:
        if r.get("reference_evaluation_admission_status") != "ADMITTED":
            continue
        status = r.get("public_eval_access_preflight_status", r.get("access_preflight_status"))
        if status in _COUNTING_ACCESS_PREFLIGHT_STATUSES:
            count += 1
    return count
