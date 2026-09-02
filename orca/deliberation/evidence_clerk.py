"""
EvidenceClerk (Phase 6 spec §17). Does NOT decide the case -- reports on
evidence state. Reuses Truth Fabric outputs directly; never re-runs
verification logic Truth Fabric already computed.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EvidenceReport:
    claims_with_evidence: list[str] = field(default_factory=list)      # Argument.argument_id
    claims_missing_evidence: list[str] = field(default_factory=list)
    evidence_to_claims: dict[str, list[str]] = field(default_factory=dict)   # evidence_id -> [argument_id]
    contradiction_count: int = 0
    direct_contradiction_count: int = 0
    source_independence_summary: dict[str, int] = field(default_factory=dict)   # IndependenceState.value -> count
    freshness_summary: dict[str, int] = field(default_factory=dict)             # FreshnessLevel.value -> count
    authority_present: bool = False
    missing_evidence_note: str = ""


def build_evidence_report(claims, truth_result=None) -> EvidenceReport:
    """`claims` are orca.deliberation.contracts.Argument objects.
    `truth_result` is an orca.truth.contracts.TruthResult | None -- its
    .contradictions/.sources/.evidence are read directly, never
    re-verified (spec §17: "do not duplicate verification logic")."""
    report = EvidenceReport()
    for claim in claims:
        if claim.evidence_ids:
            report.claims_with_evidence.append(claim.argument_id)
            for eid in claim.evidence_ids:
                report.evidence_to_claims.setdefault(eid, []).append(claim.argument_id)
        else:
            report.claims_missing_evidence.append(claim.argument_id)

    if report.claims_missing_evidence:
        report.missing_evidence_note = f"{len(report.claims_missing_evidence)} claim(s) cite no evidence at all"

    if truth_result is not None:
        contradictions = getattr(truth_result, "contradictions", None) or []
        report.contradiction_count = len(contradictions)
        report.direct_contradiction_count = sum(
            1 for c in contradictions if getattr(c, "relationship", None) is not None and getattr(c.relationship, "value", "") == "DIRECT_CONTRADICTION"
        )
        for source in getattr(truth_result, "sources", None) or []:
            key = getattr(getattr(source, "independence", None), "value", "UNKNOWN")
            report.source_independence_summary[key] = report.source_independence_summary.get(key, 0) + 1
            if getattr(getattr(source, "quality", None), "is_official", False) or getattr(getattr(source, "quality", None), "is_primary", False):
                report.authority_present = True
        for ev in getattr(truth_result, "evidence", None) or []:
            key = getattr(getattr(ev, "freshness", None), "value", "UNKNOWN")
            report.freshness_summary[key] = report.freshness_summary.get(key, 0) + 1

    return report
