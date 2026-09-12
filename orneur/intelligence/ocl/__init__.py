"""
ORNEUR Cognitive Language (OCL) V1 -- the typed, evidence-bearing,
model-independent Cognitive Intermediate Representation for ORNEUR's
native intelligence architecture (Phase 17).

See docs/orneur/phase-17/PHASE17_OCL_MASTER_SPEC_V1.md for the full
normative specification. This module is intentionally a thin export
surface; all behavior lives in the focused submodules it re-exports from.
"""
from orneur.intelligence.ocl.artifact import CognitiveArtifact
from orneur.intelligence.ocl.causal import CausalHypothesis, CounterfactualBranch
from orneur.intelligence.ocl.compiler import compile_artifact
from orneur.intelligence.ocl.diff import CognitiveDiff, diff
from orneur.intelligence.ocl.enums import (
    AtomKind,
    EvidenceKind,
    ObserverView,
    ProducerKind,
    RelationKind,
    SourceClass,
    TransformationOperation,
)
from orneur.intelligence.ocl.evidence import EvidenceAnchor
from orneur.intelligence.ocl.graph import CognitiveAtom, CognitiveRelation
from orneur.intelligence.ocl.observer import project
from orneur.intelligence.ocl.proposals import ActionIntent, EscalationRequest, VerificationContract
from orneur.intelligence.ocl.provenance import ModelIdentityRef, Provenance
from orneur.intelligence.ocl.transformations import AtomDisposition, TransformationRecord, validate_conservation
from orneur.intelligence.ocl.trust import CompilationTrustContext
from orneur.intelligence.ocl.version import CURRENT_SCHEMA_VERSION

__all__ = [
    "CognitiveArtifact", "CausalHypothesis", "CounterfactualBranch", "compile_artifact",
    "CognitiveDiff", "diff", "AtomKind", "EvidenceKind", "ObserverView", "ProducerKind",
    "RelationKind", "SourceClass", "TransformationOperation", "EvidenceAnchor",
    "CognitiveAtom", "CognitiveRelation", "project", "ActionIntent", "EscalationRequest",
    "VerificationContract", "ModelIdentityRef", "Provenance", "TransformationRecord",
    "AtomDisposition", "validate_conservation", "CompilationTrustContext", "CURRENT_SCHEMA_VERSION",
]
