"""
Deterministic, human-readable explanation of an EpistemicAssessment.
Only explains the structured epistemic basis already present on the
assessment (state/polarity/reason codes/evidence refs) -- never
reconstructs or exposes private model chain-of-thought, which OCL never
stores in the first place.
"""
from __future__ import annotations

from orneur.intelligence.epistemic.models import EpistemicAssessment


def explain_assessment(assessment: EpistemicAssessment) -> str:
    lines = [f"{assessment.state.value} / {assessment.polarity.value}"]

    if assessment.direct_support_evidence_refs:
        lines.append(f"Direct verified support: {', '.join(assessment.direct_support_evidence_refs)}")
    if assessment.direct_refutation_evidence_refs:
        lines.append(f"Direct verified refutation: {', '.join(assessment.direct_refutation_evidence_refs)}")
    if assessment.derived_support_atom_refs:
        lines.append(f"Derived support via: {', '.join(assessment.derived_support_atom_refs)}")
    if assessment.derived_refutation_atom_refs:
        lines.append(f"Derived refutation via: {', '.join(assessment.derived_refutation_atom_refs)}")
    if assessment.unresolved_evidence_refs:
        lines.append(f"Unresolved evidence: {', '.join(assessment.unresolved_evidence_refs)}")
    if assessment.contradiction_atom_refs:
        lines.append(f"Contradicting atoms: {', '.join(assessment.contradiction_atom_refs)}")
    if assessment.reason_codes:
        lines.append(f"Reason codes: {', '.join(code.value for code in assessment.reason_codes)}")
    if len(lines) == 1:
        lines.append("No qualified evidence, derivation, or feasibility basis was available.")

    return "\n".join(lines)
