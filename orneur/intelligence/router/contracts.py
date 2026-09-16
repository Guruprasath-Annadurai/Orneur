"""
Phase 20 structured contracts. All frozen dataclasses. Reuses Phase 18's
EpistemicState (never redefined) and Phase 19's IntegrityStatus (never
redefined) directly.

`CognitiveTaskProfile` is the UNTRUSTED, caller-supplied task
description. `IntelligenceCapabilityProfile` is the TRUSTED,
code/config-defined capability description of one cognitive family --
never accepted from an untrusted request (see registry.py). A caller
may supply `preferred_family` as a REQUEST, never as capability proof;
eligibility is decided exclusively from the trusted registry.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType

from orneur.intelligence.epistemic import EpistemicState
from orneur.intelligence.integrity import IntegrityStatus
from orneur.intelligence.router.enums import (
    CognitiveFamily,
    CognitiveRequirementKind,
    CognitiveRole,
    RoutingReasonCode,
    RoutingStatus,
    RuntimeAvailability,
    RuntimeLifecycleState,
)


@dataclass(frozen=True)
class CognitiveTaskProfile:
    """The untrusted structured task/cognitive-work description Phase 20
    evaluates. `material_epistemic_atom_ids` is the explicit scope of
    atoms (from the trusted overlay) materially relevant to this
    task -- Phase 20 does not and cannot infer materiality from free-form
    intent, exactly mirroring Phase 19's Cognitive Conservation doctrine."""

    task_id: str
    requirements: frozenset[CognitiveRequirementKind] = frozenset()
    material_epistemic_atom_ids: tuple[str, ...] = ()
    preferred_family: CognitiveFamily | None = None
    metadata: MappingProxyType = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True)
class IntelligenceCapabilityProfile:
    """TRUSTED, code/config-defined capability description of one
    cognitive family. Never constructed from untrusted request data."""

    family: CognitiveFamily
    role: CognitiveRole
    supported_requirements: frozenset[CognitiveRequirementKind]
    lifecycle_state: RuntimeLifecycleState
    runtime_availability: RuntimeAvailability


@dataclass(frozen=True)
class MaterialEpistemicFactor:
    """Preserves (Cognitive Conservation) the epistemic state of one
    material atom that influenced this routing decision -- so a
    consumer can never see 'GENESIS selected' without also seeing that
    an atom was UNCERTAIN, if that is what actually happened."""

    atom_id: str
    epistemic_state: EpistemicState


@dataclass(frozen=True)
class RoutingCandidateEvaluation:
    family: CognitiveFamily
    eligible: bool
    role: CognitiveRole
    rejection_reasons: tuple[RoutingReasonCode, ...] = ()


@dataclass(frozen=True)
class RoutingDecision:
    """The canonical, auditable routing receipt. Grants NO authority --
    see docs/PHASE20_INTELLIGENCE_ROUTER.md's non-authority doctrine."""

    protocol_version: str
    decision_id: str
    task_id: str
    status: RoutingStatus
    primary_family: CognitiveFamily | None
    mandatory_review_family: CognitiveFamily | None
    candidate_evaluations: tuple[RoutingCandidateEvaluation, ...] = ()
    reason_codes: tuple[RoutingReasonCode, ...] = ()
    material_epistemic_factors: tuple[MaterialEpistemicFactor, ...] = ()
    integrity_status: IntegrityStatus | None = None
    source_artifact_digest: str = ""
    source_overlay_digest: str = ""
    task_digest: str = ""
    registry_digest: str = ""
    metadata: MappingProxyType = field(default_factory=lambda: MappingProxyType({}))
