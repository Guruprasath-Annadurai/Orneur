"""
CognitiveArtifact -- the top-level OCL object (spec section 8.1). A
frozen, versioned, typed cognitive graph plus its proposal/evidence
collections. Deliberately has NO authority-bearing field anywhere in this
shape -- see `compiler.py` for the structural checks that keep it that
way, and `errors.ForbiddenAuthorityConstruct` for what happens if one
sneaks in via `metadata`.

An uncompiled `CognitiveArtifact` instance is a plain, mutable-by-Python
frozen dataclass; it only becomes a validated, canonical artifact after
`compiler.compile_artifact()` accepts it (spec section 24: Builder ->
Compiler -> Validated Immutable CognitiveArtifact).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from orneur.intelligence.ocl.causal import CausalHypothesis, CounterfactualBranch
from orneur.intelligence.ocl.evidence import EvidenceAnchor
from orneur.intelligence.ocl.graph import CognitiveAtom, CognitiveRelation
from orneur.intelligence.ocl.proposals import ActionIntent, EscalationRequest, VerificationContract
from orneur.intelligence.ocl.provenance import Provenance


@dataclass(frozen=True)
class CognitiveArtifact:
    artifact_id: str
    schema_version: str
    request_id: str
    provenance: Provenance
    created_at: str  # ISO-8601, explicitly injected -- never generated inside canonicalize()
    atoms: tuple[CognitiveAtom, ...] = field(default_factory=tuple)
    relations: tuple[CognitiveRelation, ...] = field(default_factory=tuple)
    evidence: tuple[EvidenceAnchor, ...] = field(default_factory=tuple)
    action_intents: tuple[ActionIntent, ...] = field(default_factory=tuple)
    verification_contracts: tuple[VerificationContract, ...] = field(default_factory=tuple)
    escalation_requests: tuple[EscalationRequest, ...] = field(default_factory=tuple)
    causal_hypotheses: tuple[CausalHypothesis, ...] = field(default_factory=tuple)
    counterfactual_branches: tuple[CounterfactualBranch, ...] = field(default_factory=tuple)
    limitation_atom_refs: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict = field(default_factory=dict)
    parent_artifact_id: str | None = None
    transformation_id: str | None = None
