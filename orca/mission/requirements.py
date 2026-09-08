"""
Requirement Compiler (Phase 15 spec section 5).

Every material requirement in the Phase 15 spec gets a stable ID and
must map to real, testable acceptance criteria -- a requirement with
no acceptance criteria is rejected at registration time, not merely
discouraged in prose. Status only advances forward
(UNIMPLEMENTED -> IMPLEMENTED -> VERIFIED); IMPLEMENTED requires at
least one real implementation file reference, VERIFIED requires at
least one test file reference AND an evidence reference -- this is
"no fake completion" (spec section 17) enforced structurally on the
requirement registry itself, not just as an instruction to a model.

This module is pure state -- it does not run tests or inspect the
filesystem to confirm a referenced file actually exists (that
integration belongs to the Verification Engine, Phase 15.8). What it
guarantees is that the STATE TRANSITIONS themselves are honest: you
cannot mark a requirement VERIFIED without having supplied both a
test reference and an evidence reference in the same call.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from enum import Enum


class RequirementStatus(Enum):
    UNIMPLEMENTED = "UNIMPLEMENTED"
    IMPLEMENTED = "IMPLEMENTED"
    VERIFIED = "VERIFIED"


# Forward-only transition table -- no skipping IMPLEMENTED, no moving
# backward silently. A requirement found to be broken after VERIFIED
# is handled by registering a NEW requirement revision or by an
# explicit regression record (Phase 15.8+), not by mutating history.
_ALLOWED_TRANSITIONS: dict[RequirementStatus, frozenset[RequirementStatus]] = {
    RequirementStatus.UNIMPLEMENTED: frozenset({RequirementStatus.IMPLEMENTED}),
    RequirementStatus.IMPLEMENTED: frozenset({RequirementStatus.VERIFIED}),
    RequirementStatus.VERIFIED: frozenset(),
}

_ID_PATTERN = re.compile(r"^REQ-[A-Z][A-Z0-9]*-[A-Z][A-Z0-9]*-\d{3}$")


class RequirementError(Exception):
    """Raised on a malformed requirement or an invalid lifecycle transition."""


@dataclass(frozen=True)
class Requirement:
    id: str
    source_section: str          # e.g. "spec section 6" -- traces back to the persisted spec
    statement: str                # what must be true, in the requirement's own words
    acceptance_criteria: tuple[str, ...]
    status: RequirementStatus = RequirementStatus.UNIMPLEMENTED
    implementation_files: tuple[str, ...] = field(default_factory=tuple)
    test_files: tuple[str, ...] = field(default_factory=tuple)
    evidence_ref: str | None = None

    def __post_init__(self) -> None:
        if not _ID_PATTERN.match(self.id):
            raise RequirementError(
                f"Requirement ID {self.id!r} does not match REQ-<AREA>-<NAME>-<NNN> "
                f"(e.g. REQ-MISSION-STATES-001)."
            )
        if not self.statement.strip():
            raise RequirementError(f"{self.id}: statement must not be empty.")
        if not self.acceptance_criteria or any(not c.strip() for c in self.acceptance_criteria):
            raise RequirementError(
                f"{self.id}: at least one non-empty acceptance criterion is required -- "
                f"spec section 5: 'a requirement must map to executable/testable acceptance criteria.'"
            )


_REGISTRY: dict[str, Requirement] = {}


def register(req: Requirement) -> Requirement:
    """Adds a requirement to the registry. Raises if the ID is already
    registered -- requirement IDs are stable and unique for the life
    of the project; a changed requirement gets a new ID (e.g. -002),
    it does not silently overwrite -001's history."""
    if req.id in _REGISTRY:
        raise RequirementError(f"{req.id} is already registered -- requirement IDs are immutable once created.")
    _REGISTRY[req.id] = req
    return req


def get(req_id: str) -> Requirement:
    try:
        return _REGISTRY[req_id]
    except KeyError:
        raise RequirementError(f"No such requirement: {req_id}") from None


def all_requirements() -> tuple[Requirement, ...]:
    return tuple(_REGISTRY.values())


def by_status(status: RequirementStatus) -> tuple[Requirement, ...]:
    return tuple(r for r in _REGISTRY.values() if r.status == status)


def transition(
    req_id: str,
    new_status: RequirementStatus,
    *,
    implementation_files: tuple[str, ...] = (),
    test_files: tuple[str, ...] = (),
    evidence_ref: str | None = None,
) -> Requirement:
    """Advances a requirement's status. Enforces:
      - forward-only movement (see _ALLOWED_TRANSITIONS);
      - IMPLEMENTED requires >=1 implementation_files (merged with any
        already recorded);
      - VERIFIED requires >=1 test_files AND a non-empty evidence_ref
        (merged/required in this same call, matching spec section 17's
        "IMPLEMENTATION: COMPLETE / VERIFICATION: UNVERIFIED" distinction
        -- a requirement cannot become VERIFIED by assertion alone).
    Returns the updated Requirement (registry is updated in place)."""
    current = get(req_id)
    if new_status not in _ALLOWED_TRANSITIONS[current.status]:
        raise RequirementError(
            f"{req_id}: cannot transition {current.status.value} -> {new_status.value}. "
            f"Allowed from {current.status.value}: "
            f"{sorted(s.value for s in _ALLOWED_TRANSITIONS[current.status]) or 'none (terminal)'}."
        )

    merged_impl = tuple(dict.fromkeys(current.implementation_files + implementation_files))
    merged_tests = tuple(dict.fromkeys(current.test_files + test_files))

    if new_status is RequirementStatus.IMPLEMENTED and not merged_impl:
        raise RequirementError(
            f"{req_id}: IMPLEMENTED requires at least one implementation file reference."
        )
    if new_status is RequirementStatus.VERIFIED:
        if not merged_tests:
            raise RequirementError(f"{req_id}: VERIFIED requires at least one test file reference.")
        if not (evidence_ref or "").strip():
            raise RequirementError(
                f"{req_id}: VERIFIED requires a non-empty evidence_ref -- "
                f"spec section 18: Production Proof must never invent evidence."
            )

    updated = replace(
        current,
        status=new_status,
        implementation_files=merged_impl,
        test_files=merged_tests,
        evidence_ref=evidence_ref or current.evidence_ref,
    )
    _REGISTRY[req_id] = updated
    return updated


def reset_registry_for_tests() -> None:
    """Test-only helper -- clears the module-level registry so test
    files can register their own fixtures without colliding with the
    real Phase 15 requirement seed data (see seed_registry())."""
    _REGISTRY.clear()
