"""C27 / class-K technical feasibility investigation.

Does not implement an unauthorized class-K recovery workaround.
Does not invent R65 policy text. Does not waive C27.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ClassKFeasibility:
    requirement_id: str
    title: str
    software_semantics_available: bool
    unauthorized_workaround_refused: bool
    physical_prerequisite: str
    founder_prerequisite: str
    engineering_disposition: str
    summary: str

    def to_dict(self) -> dict:
        return asdict(self)


def investigate_c27() -> ClassKFeasibility:
    """Record what engineering can and cannot do for C27 today."""
    return ClassKFeasibility(
        requirement_id="C27",
        title="TPM/board replacement re-enrolment refusing lower-generation restore",
        software_semantics_available=True,
        unauthorized_workaround_refused=True,
        physical_prerequisite=(
            "Authorized class-K path on real TPM/board hardware producing "
            "re-enrolment records that refuse lower-generation restore"
        ),
        founder_prerequisite=(
            "Founder-authorized class-K recovery policy/path; engineering must not "
            "self-authorize a recovery shortcut"
        ),
        engineering_disposition="BLOCKED_BY_PROTECTED_DECISION",
        summary=(
            "Software can model generation counters and refuse a lower generation in "
            "synthetic tests, but C27 acceptance requires authorized class-K "
            "re-enrolment records from real hardware. Shipping a local counter file "
            "or mock TPM as PASS would be an unauthorized workaround and is refused."
        ),
    )


def refuse_unauthorized_class_k_workaround(*, claimed_pass: bool, authorized_path: bool) -> None:
    """Raise if a caller attempts to mark C27 complete without an authorized path."""
    if claimed_pass and not authorized_path:
        raise PermissionError(
            "C27 cannot be marked complete without an authorized class-K path; "
            "unauthorized recovery workaround refused"
        )
