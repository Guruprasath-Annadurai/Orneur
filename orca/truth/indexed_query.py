"""Authorized retrieval through the Truth Fabric evidence contract.

`orca.rag_x.execute` is not called. Claim state uses the lexical thresholds
in `orca.truth.verification`. The entailment judge is not consulted, so this
path never reports full `SUPPORTED`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from orca.truth.access import AccessDenied, TrustedSession
from orca.truth.contracts import ClaimSupport, ClaimSupportState
from orca.truth.evidence import evidence_from_document_chunk
from orca.truth.verification import _LEXICAL_STRONG_THRESHOLD, _LEXICAL_WEAK_THRESHOLD, _lexical_overlap

_FACT = re.compile(r"([A-Za-z][A-Za-z0-9_]*)\s*=\s*([A-Za-z0-9_.:-]+)")


@dataclass(frozen=True)
class AuthorizedAnswer:
    query: str
    tenant_id: str
    principal_id: str
    hits: tuple
    evidence: tuple
    sources: tuple
    abstained: bool
    contradictions: tuple[str, ...]
    claim_support: ClaimSupport | None
    tool_grant: bool
    partial_reasons: tuple[str, ...]
    method: str
    dense_backend: str
    production_neural: bool
    judge_consulted: bool
    ignored_claims: tuple[str, ...]


def fact_conflicts(texts: list[str]) -> list[str]:
    found: dict[str, set[str]] = {}
    for text in texts:
        for key, value in _FACT.findall(text):
            found.setdefault(key, set()).add(value)
    return [f"{key}={'/'.join(sorted(values))}" for key, values in sorted(found.items()) if len(values) > 1]


def lexical_claim_support(claim_id: str, claim_text: str, evidence: list) -> ClaimSupport:
    """Same fallback as `verify_claim` when the judge is absent.

    Full `SUPPORTED` is intentionally unreachable here.
    """
    if not evidence:
        return ClaimSupport(
            claim_id=claim_id, evidence_ids=[], support_state=ClaimSupportState.UNSUPPORTED,
            reasons=["no evidence available to check this claim against"],
        )
    overlaps = [(ev, _lexical_overlap(claim_text, ev.passage.text)) for ev in evidence]
    overlaps.sort(key=lambda pair: pair[1], reverse=True)
    best_evidence, best_overlap = overlaps[0]
    evidence_ids = [ev.evidence_id for ev, overlap in overlaps if overlap >= _LEXICAL_WEAK_THRESHOLD] or [best_evidence.evidence_id]
    if best_overlap >= _LEXICAL_STRONG_THRESHOLD:
        state = ClaimSupportState.PARTIALLY_SUPPORTED
        reason = "judge unavailable -- strong lexical overlap only, entailment not confirmed"
    elif best_overlap >= _LEXICAL_WEAK_THRESHOLD:
        state = ClaimSupportState.UNKNOWN
        reason = "judge unavailable -- weak lexical overlap, cannot determine support"
    else:
        state = ClaimSupportState.UNSUPPORTED
        reason = "judge unavailable -- no meaningful lexical overlap with any evidence"
    return ClaimSupport(
        claim_id=claim_id, evidence_ids=evidence_ids, support_state=state,
        support_strength=f"lexical_overlap={best_overlap:.2f}", reasons=[reason],
    )


def run_authorized_retrieval(
    session: TrustedSession,
    index,
    query: str,
    *,
    claim: str | None = None,
    top_k: int = 5,
    deadline_s: float | None = None,
    claimed_tenant: str | None = None,
) -> AuthorizedAnswer:
    """Retrieve, compile evidence, and refuse tool authority from the text."""
    if not index.permits(session):
        raise AccessDenied("trusted session does not permit this index")
    report = index.search(
        session, query, top_k=top_k, deadline_s=deadline_s, claimed_tenant=claimed_tenant,
    )
    evidence = []
    sources = []
    for hit in report.hits:
        ev, src = evidence_from_document_chunk(
            {"text": hit.text, "filename": hit.filename, "chunk_idx": hit.chunk_idx},
            session.session_id,
        )
        evidence.append(ev)
        sources.append(src)
    conflicts = fact_conflicts([hit.text for hit in report.hits])
    abstained = bool(conflicts)
    claim_support = None
    if claim is not None and abstained:
        claim_support = ClaimSupport(
            claim_id="claim-1",
            evidence_ids=[ev.evidence_id for ev in evidence],
            support_state=ClaimSupportState.CONTRADICTED,
            reasons=["contradictory values in the retrieved passages; no side was selected"],
        )
    elif claim is not None:
        claim_support = lexical_claim_support("claim-1", claim, evidence)
    return AuthorizedAnswer(
        query=query,
        tenant_id=session.tenant_id,
        principal_id=session.principal_id,
        hits=tuple(report.hits),
        evidence=tuple(evidence),
        sources=tuple(sources),
        abstained=abstained,
        contradictions=tuple(conflicts),
        claim_support=claim_support,
        tool_grant=False,
        partial_reasons=tuple(report.partial_reasons),
        method=report.method,
        dense_backend=report.dense_backend,
        production_neural=report.production_neural,
        judge_consulted=False,
        ignored_claims=tuple(report.ignored_claims),
    )
