"""
Phase 18 core data shapes. All frozen dataclasses -- immutable once
constructed, mirroring orneur.intelligence.ocl's pattern. None of these
types are model-writable canonical truth: EpistemicAssessment /
EpistemicOverlay are produced ONLY by resolver.assess_artifact(), never
constructed from untrusted input and accepted as-is.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType

from orneur.intelligence.epistemic.enums import (
    EpistemicPolarity,
    EpistemicReasonCode,
    EpistemicState,
    EvidenceResolutionStatus,
    EvidenceStance,
    VerificationFeasibility,
)


@dataclass(frozen=True)
class ResolvedEvidence:
    """A trusted resolver's out-of-band resolution of one EvidenceAnchor
    reference against one target atom. Never constructed by parsing a
    model's own metadata -- always supplied explicitly by the caller of
    assess_artifact(), alongside an explicit trust context."""

    evidence_id: str
    target_atom_id: str
    status: EvidenceResolutionStatus
    stance: EvidenceStance
    resolver_reference: str
    resolved_at: str
    metadata: MappingProxyType = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True)
class VerificationFeasibilityRecord:
    """A trusted resolver's explicit statement about whether a
    proposition can be verified at all right now. Only a
    TRUSTED_DETERMINISTIC_VERIFIER-tier record may set
    STRUCTURALLY_UNVERIFIABLE (see trust.py)."""

    target_atom_id: str
    feasibility: VerificationFeasibility
    verifier_reference: str
    recorded_at: str
    metadata: MappingProxyType = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True)
class EpistemicAssessment:
    """The canonical, independently-computed epistemic assessment of one
    OCL atom, relative to the evidence/derivation/contradiction/
    feasibility basis supplied to assess_artifact()."""

    atom_id: str
    state: EpistemicState
    polarity: EpistemicPolarity
    direct_support_evidence_refs: tuple[str, ...] = ()
    direct_refutation_evidence_refs: tuple[str, ...] = ()
    derived_support_atom_refs: tuple[str, ...] = ()
    derived_refutation_atom_refs: tuple[str, ...] = ()
    unresolved_evidence_refs: tuple[str, ...] = ()
    contradiction_atom_refs: tuple[str, ...] = ()
    verification_contract_refs: tuple[str, ...] = ()
    reason_codes: tuple[EpistemicReasonCode, ...] = ()


@dataclass(frozen=True)
class EpistemicOverlay:
    """A deterministic assessment of one exact, canonical OCL
    CognitiveArtifact, bound to it by source_artifact_id +
    source_artifact_digest. Never silently reused against a different
    or mutated artifact (see resolver.verify_overlay_binding)."""

    overlay_id: str
    schema_version: str
    source_artifact_id: str
    source_artifact_digest: str
    assessment_context_digest: str
    assessed_at: str
    assessments: tuple[EpistemicAssessment, ...] = ()
    metadata: MappingProxyType = field(default_factory=lambda: MappingProxyType({}))
