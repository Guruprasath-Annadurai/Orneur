"""
CausalHypothesis + CounterfactualBranch (spec sections 8.8-8.9). A model-
produced causal edge is ALWAYS a hypothesis, never established causality --
OCL has no mechanism to upgrade one to fact; only an externally-issued
EvidenceAnchor referenced by `observed_evidence_refs` can do that, and even
then the upgrade decision belongs to a future phase (Phase 18 epistemic
semantics), not to OCL itself.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CausalHypothesis:
    hypothesis_id: str
    cause_atom_ref: str
    mechanism: str
    predicted_consequence_atom_ref: str
    observable_test_ref: str | None = None
    observed_evidence_refs: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CounterfactualBranch:
    """IF `condition_atom_ref` differed THEN `predicted_atom_ref` should
    differ BECAUSE `causal_hypothesis_ref`."""
    branch_id: str
    causal_hypothesis_ref: str
    condition_atom_ref: str
    predicted_atom_ref: str
