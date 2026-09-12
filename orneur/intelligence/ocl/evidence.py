"""
EvidenceAnchor (spec section 8.4). OCL REFERENCES evidence; it never
creates it. No secret/sensitive content is ever copied into an anchor --
prefer a locator/digest over raw content.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from orneur.intelligence.ocl.enums import EvidenceKind


@dataclass(frozen=True)
class EvidenceAnchor:
    evidence_id: str
    evidence_kind: EvidenceKind
    issuer: str                        # who/what produced the underlying evidence
    reference: str                     # opaque locator/ID into the issuing system -- never raw secret content
    digest: str | None = None          # integrity reference where the issuing system supports one
    observed_at: str | None = None     # ISO-8601 freshness timestamp reference
    locator: str | None = None
    metadata: dict = field(default_factory=dict)
