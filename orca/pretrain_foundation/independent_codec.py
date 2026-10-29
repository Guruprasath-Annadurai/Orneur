"""C16 independent codec compatibility gate.

A second codec implementation, not Cursor's, must agree on the OCR1
verdict vector. This module refuses Cursor self-certification as the
second implementation.
"""
from __future__ import annotations

from dataclasses import dataclass


class IndependentCodecError(Exception):
    """Second-implementation evidence is missing or self-referential."""


CURSOR_IMPLEMENTATION_IDS = frozenset({
    "cursor",
    "orca.rse.imp1.codec",
    "orca.rse.imp4.ocr1",
    "orneur-cursor",
})


@dataclass(frozen=True)
class CodecAgreementClaim:
    primary_implementation_id: str
    secondary_implementation_id: str
    primary_verdict_digest: str
    secondary_verdict_digest: str
    vector_id: str


def validate_independent_agreement(claim: CodecAgreementClaim) -> None:
    if not claim.secondary_implementation_id:
        raise IndependentCodecError("secondary codec implementation id required")
    if claim.secondary_implementation_id.lower() in CURSOR_IMPLEMENTATION_IDS:
        raise IndependentCodecError(
            "Cursor/ORNEUR primary codec cannot self-certify as the independent second implementation"
        )
    if claim.secondary_implementation_id == claim.primary_implementation_id:
        raise IndependentCodecError("primary and secondary implementation ids must differ")
    if not claim.primary_verdict_digest or not claim.secondary_verdict_digest:
        raise IndependentCodecError("both verdict digests are required")
    if claim.primary_verdict_digest != claim.secondary_verdict_digest:
        raise IndependentCodecError(
            f"OCR1 verdict digests disagree for vector {claim.vector_id}: "
            f"{claim.primary_verdict_digest} != {claim.secondary_verdict_digest}"
        )


def c16_engineering_status(*, secondary_present: bool) -> str:
    if not secondary_present:
        return "IMPLEMENTED_UNVERIFIED_PRIMARY_ONLY — awaiting independent second codec"
    return "ENGINEERING_COMPLETE — AWAITING_INDEPENDENT_REVIEW"
