"""
Phase 18 -- Epistemic State.

A deterministic, typed, inspectable, evidence-grounded representation of
what a cognitive proposition's knowledge state is, computed
independently from Phase 17 OCL artifacts. This package grants NO
authority: EpistemicState/EpistemicOverlay objects are DATA, never
execution/policy/Court/approval/verification-truth/promotion/tool/
budget/release grants. Consult
docs/orneur/phase-18/PHASE18_EPISTEMIC_STATE_SPEC.md for the full
doctrine and algorithm.

Only intentional public contracts are exported here.
"""
from __future__ import annotations

from orneur.intelligence.epistemic.canonical import canonicalize, digest, to_canonical_json
from orneur.intelligence.epistemic.diff import EpistemicDiff, EpistemicTransition, diff
from orneur.intelligence.epistemic.enums import (
    CURRENT_SCHEMA_VERSION,
    EPISTEMICALLY_ASSESSABLE_ATOM_KINDS,
    RELATION_EPISTEMIC_SEMANTICS,
    EpistemicPolarity,
    EpistemicReasonCode,
    EpistemicResolutionTrustContext,
    EpistemicState,
    EvidenceResolutionStatus,
    EvidenceStance,
    RelationEffect,
    RelationEpistemicSemantics,
    VerificationFeasibility,
    get_relation_semantics,
)
from orneur.intelligence.epistemic.explain import explain_assessment
from orneur.intelligence.epistemic.models import (
    EpistemicAssessment,
    EpistemicOverlay,
    ResolvedEvidence,
    VerificationFeasibilityRecord,
)
from orneur.intelligence.epistemic.resolver import assess_artifact, verify_overlay_binding

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "EPISTEMICALLY_ASSESSABLE_ATOM_KINDS",
    "RELATION_EPISTEMIC_SEMANTICS",
    "EpistemicAssessment",
    "EpistemicDiff",
    "EpistemicOverlay",
    "EpistemicPolarity",
    "EpistemicReasonCode",
    "EpistemicResolutionTrustContext",
    "EpistemicState",
    "EpistemicTransition",
    "EvidenceResolutionStatus",
    "EvidenceStance",
    "RelationEffect",
    "RelationEpistemicSemantics",
    "ResolvedEvidence",
    "VerificationFeasibility",
    "VerificationFeasibilityRecord",
    "assess_artifact",
    "canonicalize",
    "diff",
    "digest",
    "explain_assessment",
    "get_relation_semantics",
    "to_canonical_json",
    "verify_overlay_binding",
]
