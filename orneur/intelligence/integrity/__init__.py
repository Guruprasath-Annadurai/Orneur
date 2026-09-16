"""
Phase 19 -- Epistemic Integrity Protocol.

Consumes Phase 17 OCL (read-only) and Phase 18 Epistemic State
(read-only) to deterministically judge whether a STRUCTURED proposed
answer/assertion contract is permitted to present each proposition at
its proposed epistemic strength, or must be weakened/qualified/blocked.

Phase 19 grants NO authority: an IntegrityReceipt is DATA, never
execution/policy/Court/human-approval/verification-truth/model-
promotion/tool/budget/release authority. It does not call any model,
tool, or the router. It does not begin Phase 20 (Intelligence Router).

Consult docs/orneur/phase-19/PHASE19_EPISTEMIC_INTEGRITY_SPEC.md for the
full doctrine, hard-floor state matrix, and non-goals (notably: this
protocol validates structured cognitive assertions, not arbitrary
unconstrained natural-language prose).

Only intentional public contracts are exported here.
"""
from __future__ import annotations

from orneur.intelligence.integrity.canonical import canonicalize, digest, to_canonical_json
from orneur.intelligence.integrity.contracts import (
    AssertionAssessment,
    DisclosureRequirement,
    IntegrityPolicy,
    IntegrityProposal,
    IntegrityReceipt,
    IntegrityViolation,
    ProposedAssertion,
)
from orneur.intelligence.integrity.enums import (
    BLOCKING_VIOLATION_REASONS,
    CURRENT_PROTOCOL_VERSION,
    IntegrityObligation,
    IntegrityStatus,
    IntegrityViolationReason,
    PresentationTreatment,
)
from orneur.intelligence.integrity.evaluator import assess_integrity, require_integrity
from orneur.intelligence.integrity.floor import (
    HARD_FLOOR_MAXIMUM_TREATMENT,
    HARD_FLOOR_PERMITTED_TREATMENTS,
    MATERIAL_CONSERVATION_STATES,
    STATE_REQUIRED_OBLIGATION,
    effective_permitted_treatments,
)

__all__ = [
    "BLOCKING_VIOLATION_REASONS",
    "CURRENT_PROTOCOL_VERSION",
    "HARD_FLOOR_MAXIMUM_TREATMENT",
    "HARD_FLOOR_PERMITTED_TREATMENTS",
    "MATERIAL_CONSERVATION_STATES",
    "STATE_REQUIRED_OBLIGATION",
    "AssertionAssessment",
    "DisclosureRequirement",
    "IntegrityObligation",
    "IntegrityPolicy",
    "IntegrityProposal",
    "IntegrityReceipt",
    "IntegrityStatus",
    "IntegrityViolation",
    "IntegrityViolationReason",
    "PresentationTreatment",
    "ProposedAssertion",
    "assess_integrity",
    "canonicalize",
    "digest",
    "effective_permitted_treatments",
    "require_integrity",
    "to_canonical_json",
]
