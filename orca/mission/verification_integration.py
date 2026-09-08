"""
Phase 15.8 -- the STRICTER criterion-verification path (spec section
16).

Phase 15.7's `orca.mission.acceptance_criteria.transition_criterion()`
allowed a caller to pass ANY non-empty string as `evidence_ref` when
moving a criterion to VERIFIED -- sufficient for Phase 15.7's own
scope, but not strong enough for Phase 15.8: a caller could type
"trust me" as the evidence_ref and the old path would accept it.

This module does NOT remove or weaken that existing path (Phase
15.7's own tests still exercise it unchanged). It ADDS
`verify_criterion_via_verification_record()`, which requires a REAL,
already-recorded `VerificationRecord` whose `outcome` is PASS and
whose `requirement_id`/`criterion_id` genuinely match the criterion
being verified -- there is no way to reach VERIFIED through this path
without a real Verifier having produced a real PASS observation
first.
"""
from __future__ import annotations

from orca.mission.acceptance_criteria import (
    AcceptanceCriterion,
    CriterionError,
    CriterionStatus,
    get_criterion,
    transition_criterion,
)
from orca.mission.verification import VerificationOutcome, VerificationRecord


class VerificationIntegrationError(Exception):
    pass


def verify_criterion_via_verification_record(
    criterion_id: str, record: VerificationRecord,
) -> AcceptanceCriterion:
    """The ONLY strict path to VERIFIED that this module offers.
    Requires `record.outcome is VerificationOutcome.PASS` AND that
    `record.criterion_id == criterion_id` -- a PASS record for a
    DIFFERENT criterion (even under the same requirement) is rejected,
    exactly mirroring Phase 15.5's own lease-scope-binding discipline
    ("a lease issued for operation A cannot authorize operation B")."""
    criterion = get_criterion(criterion_id)

    if record.outcome is not VerificationOutcome.PASS:
        raise VerificationIntegrationError(
            f"{criterion_id}: verification record {record.id} has outcome "
            f"{record.outcome.value}, not PASS -- cannot verify a criterion from a non-passing record."
        )
    if record.criterion_id != criterion_id:
        raise VerificationIntegrationError(
            f"{criterion_id}: verification record {record.id} is scoped to criterion "
            f"{record.criterion_id!r}, not {criterion_id!r} -- a PASS record cannot verify a different criterion."
        )
    if record.requirement_id != criterion.requirement_id:
        raise VerificationIntegrationError(
            f"{criterion_id}: verification record {record.id}'s requirement_id "
            f"{record.requirement_id!r} does not match the criterion's own requirement_id "
            f"{criterion.requirement_id!r}."
        )

    if criterion.status is CriterionStatus.PENDING:
        transition_criterion(criterion_id, CriterionStatus.IMPLEMENTED)
    return transition_criterion(criterion_id, CriterionStatus.VERIFIED, evidence_ref=record.id)
