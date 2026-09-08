"""
Phase 15.8 -- typed Verification Engine core (spec sections 2-4).

    REQUIREMENT -> ACCEPTANCE CRITERION -> VERIFICATION PLAN ->
    VERIFIER -> REAL OBSERVATION -> VERIFICATION RECORD ->
    EVIDENCE ARTIFACT -> TRACEABILITY -> REQUIREMENT/MISSION DECISION

Critical invariant enforced structurally throughout this package:
MISSING EVIDENCE != PASS, and IMPLEMENTED != VERIFIED. No model
belongs in the step that turns absence into PASS -- every outcome in
this module is produced by a real Verifier observing a real
execution/comparison, never by a caller merely asserting a result.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class VerificationOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNVERIFIED = "UNVERIFIED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"


#: Outcomes that never count as evidence a requirement/criterion is
#: satisfied. Used by aggregation (spec section 17) and by the
#: acceptance-criteria integration (spec section 16) so "not PASS" has
#: exactly one authoritative definition across this package.
NON_PASSING_OUTCOMES = frozenset({
    VerificationOutcome.FAIL, VerificationOutcome.UNVERIFIED, VerificationOutcome.ERROR,
    VerificationOutcome.CANCELLED, VerificationOutcome.TIMED_OUT,
})


class VerificationError(Exception):
    pass


@dataclass(frozen=True)
class VerificationRecord:
    """Immutable in semantics: a re-run creates a NEW record (a new
    `id`), it never mutates a prior one -- history is append-only
    (spec section 3, 24). `NOT_APPLICABLE` requires a non-empty
    `not_applicable_reason`; `ERROR` requires a non-empty
    `error_detail`; every outcome has an explicit invariant checked at
    construction, not left to caller discipline."""
    id: str
    mission_id: str | None
    requirement_id: str | None
    criterion_id: str | None
    category: str
    verification_method: str
    verifier_id: str
    started_at: str
    outcome: VerificationOutcome
    revision: str | None
    finished_at: str | None = None
    verifier_version: str | None = None
    summary: str | None = None
    command_reference: str | None = None
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    artifact_hash: str | None = None
    environment_identity: str | None = None
    limitations: str | None = None
    error_detail: str | None = None
    not_applicable_reason: str | None = None

    def __post_init__(self) -> None:
        if self.outcome is VerificationOutcome.NOT_APPLICABLE and not (self.not_applicable_reason or "").strip():
            raise VerificationError(
                f"{self.id}: NOT_APPLICABLE requires a non-empty not_applicable_reason -- "
                f"it may never be the default for a merely-missing check."
            )
        if self.outcome is VerificationOutcome.ERROR and not (self.error_detail or "").strip():
            raise VerificationError(f"{self.id}: ERROR requires a non-empty error_detail.")
        if self.outcome is VerificationOutcome.PASS and not self.evidence_refs and not self.command_reference:
            raise VerificationError(
                f"{self.id}: PASS requires at least one evidence_ref or a command_reference -- "
                f"a PASS outcome must be traceable to a real observation, never asserted bare."
            )


@dataclass(frozen=True)
class RequiredCheck:
    category: str
    verification_method: str
    required: bool = True


@dataclass(frozen=True)
class VerificationPlan:
    """Defines what must be OBSERVED -- never claims a check already
    passed (spec section 4)."""
    plan_id: str
    mission_id: str | None
    requirement_ids: tuple[str, ...]
    revision: str
    checks: tuple[RequiredCheck, ...]
    created_at: str = field(default_factory=_now_iso)
    sandbox_requirement: str | None = None
    authority_requirement: str | None = None
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if not self.checks:
            raise VerificationError(f"{self.plan_id}: a VerificationPlan requires at least one check.")

    @property
    def required_checks(self) -> tuple[RequiredCheck, ...]:
        return tuple(c for c in self.checks if c.required)
