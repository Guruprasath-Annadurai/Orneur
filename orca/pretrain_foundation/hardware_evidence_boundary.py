"""Physical-security evidence boundary for Phase 6.

Synthetic unit tests may exercise software semantics. They must never be
classified as physical acceptance for TPM, Secure Boot, attestation,
Crown/Forge custody, or floor-card comparison rows.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


PHYSICAL_EVIDENCE_KINDS = frozenset({
    "tpm_policy",
    "tpm_nv",
    "measured_boot",
    "secure_boot_keys",
    "attestation_quote",
    "crown_serial_custody",
    "forge_serial_custody",
    "witness_serial_custody",
    "floor_card_serial_comparison",
    "uki_identity",
    "firmware_key_list",
    "power_cut_nv_hardware",
    "class_k_reenrolment",
})

# Register rows that require real physical receipts (engineering may implement
# software interfaces, but cannot PASS these from mocks).
PHYSICAL_REQUIREMENT_IDS = frozenset({
    "G6", "G7", "G9", "G11",
    "C22", "C23", "C24", "C25", "C26", "C27", "C28",
    "C39", "C40", "C41", "C42", "C43", "C46", "C47", "C48", "C50",
    "HW-01", "HW-02", "HW-03", "HW-06", "HW-08", "HW-11",
    "HW-16", "HW-18", "HW-19", "HW-20", "HW-21", "HW-24", "HW-FORGE",
    "P2-1", "P2-2", "P2-4",
})


class PhysicalEvidenceError(Exception):
    """Raised when a caller tries to treat synthetic evidence as physical PASS."""


@dataclass(frozen=True)
class EvidenceClaim:
    requirement_id: str
    kind: str
    synthetic: bool
    artifact_id: str | None = None
    notes: str = ""


def classify_claim(claim: EvidenceClaim) -> str:
    """Return an engineering disposition label for a physical-adjacent claim.

    Possible returns:
    - ``SYNTHETIC_SEMANTICS_ONLY`` — software path exercised; not acceptance
    - ``PHYSICAL_RECEIPT_PRESENT`` — real artifact id supplied and not synthetic
    - ``PHYSICAL_EVIDENCE_REQUIRED`` — blocked pending hardware / custody
    """
    if claim.requirement_id in PHYSICAL_REQUIREMENT_IDS or claim.kind in PHYSICAL_EVIDENCE_KINDS:
        if claim.synthetic:
            return "SYNTHETIC_SEMANTICS_ONLY"
        if claim.artifact_id:
            return "PHYSICAL_RECEIPT_PRESENT"
        return "PHYSICAL_EVIDENCE_REQUIRED"
    if claim.synthetic:
        return "SYNTHETIC_SEMANTICS_ONLY"
    return "PHYSICAL_RECEIPT_PRESENT" if claim.artifact_id else "PHYSICAL_EVIDENCE_REQUIRED"


def refuse_mock_as_acceptance(claim: EvidenceClaim) -> None:
    """Fail closed if a synthetic claim is offered as formal/physical PASS."""
    disposition = classify_claim(claim)
    if disposition == "SYNTHETIC_SEMANTICS_ONLY":
        raise PhysicalEvidenceError(
            f"refusing synthetic evidence as physical acceptance for "
            f"{claim.requirement_id}/{claim.kind}"
        )
    if disposition == "PHYSICAL_EVIDENCE_REQUIRED":
        raise PhysicalEvidenceError(
            f"physical evidence required for {claim.requirement_id}/{claim.kind}; none supplied"
        )


def engineering_status_for_ids(ids: Iterable[str]) -> dict[str, str]:
    """Map requirement ids to honest Phase-6 engineering labels."""
    out: dict[str, str] = {}
    for rid in ids:
        if rid in PHYSICAL_REQUIREMENT_IDS:
            out[rid] = "BLOCKED_PENDING_PHYSICAL_OR_CUSTODY_EVIDENCE"
        else:
            out[rid] = "NOT_PHYSICAL_GATE"
    return out
