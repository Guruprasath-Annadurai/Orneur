"""Typed claim, evidence, denial, and promotion records.

An agent result is not proof. VERIFIED is reachable only when a different
actor supplies a passing verification and an evidence span whose digest
matches its bytes. This module does not execute tools and does not train.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

EPISTEMIC_STATES = frozenset({
    "OBSERVED",
    "VERIFIED",
    "INFERRED",
    "DISPUTED",
    "UNKNOWN",
    "REFUTED",
    "STALE",
})


class EvidenceContractError(Exception):
    """The evidence contract refused the transition."""


@dataclass(frozen=True)
class EvidenceSpan:
    source_id: str
    span: str
    digest: str
    authorized: bool

    def matches(self) -> bool:
        actual = hashlib.sha256(self.span.encode("utf-8")).hexdigest()
        return actual == self.digest and bool(self.source_id)


def evidence_span(source_id: str, span: str, *, authorized: bool) -> EvidenceSpan:
    digest = hashlib.sha256(span.encode("utf-8")).hexdigest()
    return EvidenceSpan(source_id=source_id, span=span, digest=digest, authorized=authorized)


@dataclass(frozen=True)
class Claim:
    claim_id: str
    text: str
    state: str
    producer_id: str
    evidence: tuple[EvidenceSpan, ...] = ()
    verifier_id: str | None = None
    verification_outcome: str | None = None

    def __post_init__(self) -> None:
        if self.state not in EPISTEMIC_STATES:
            raise EvidenceContractError(f"unknown epistemic state {self.state}")


def transition(
    claim: Claim,
    new_state: str,
    *,
    actor_id: str,
    evidence: tuple[EvidenceSpan, ...] | None = None,
    outcome: str | None = None,
) -> Claim:
    """Move a claim. The producer cannot mark its own claim VERIFIED."""
    if new_state not in EPISTEMIC_STATES:
        raise EvidenceContractError(f"unknown epistemic state {new_state}")
    if not actor_id:
        raise EvidenceContractError("actor_id is required")
    spans = claim.evidence if evidence is None else evidence
    if new_state == "VERIFIED":
        if actor_id == claim.producer_id:
            raise EvidenceContractError("producer cannot verify its own claim")
        if outcome != "passed":
            raise EvidenceContractError("verification outcome is not passed")
        if not spans or any(not span.authorized or not span.matches() for span in spans):
            raise EvidenceContractError("verification evidence is missing or does not match")
        if any(span.span != claim.text for span in spans):
            raise EvidenceContractError("evidence span does not support the claim text")
    return Claim(
        claim_id=claim.claim_id,
        text=claim.text,
        state=new_state,
        producer_id=claim.producer_id,
        evidence=spans,
        verifier_id=actor_id if new_state == "VERIFIED" else claim.verifier_id,
        verification_outcome=outcome if new_state == "VERIFIED" else claim.verification_outcome,
    )


@dataclass(frozen=True)
class DenialReceipt:
    """A refusal on this guarded path. It does not prove every other path was idle."""

    requested_action: str
    decision: str
    reason: str
    enforcement_point: str
    evidence_digest: str
    tenant_id: str


@dataclass(frozen=True)
class PromotionProposal:
    candidate_id: str
    produced_by: str
    decided_by: str
    applied: bool = False

    def __post_init__(self) -> None:
        if self.applied:
            raise EvidenceContractError("a proposal cannot be constructed as already applied")
        if self.decided_by in {self.produced_by, self.candidate_id}:
            raise EvidenceContractError("a candidate cannot approve its own promotion")
        if not self.decided_by or not self.produced_by or not self.candidate_id:
            raise EvidenceContractError("promotion identities are required")
