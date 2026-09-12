"""
OCL V1 core enums. Every enum here is a CLOSED vocabulary for this schema
version -- an unrecognized value fails closed at compile time (never
silently coerced to a default), per PHASE17 section 15/22.
"""
from __future__ import annotations

from enum import Enum


class AtomKind(str, Enum):
    """The smallest typed cognitive semantic unit's kind. Deliberately has
    NO "FACT" member (spec section 8.2) -- an authoritative fact is always
    represented as an EvidenceAnchor reference, never as free atom text a
    model could label "fact" to borrow authority it doesn't have."""
    ASSERTION = "ASSERTION"
    OBSERVATION_REFERENCE = "OBSERVATION_REFERENCE"
    HYPOTHESIS = "HYPOTHESIS"
    ASSUMPTION = "ASSUMPTION"
    UNKNOWN = "UNKNOWN"
    CONFLICT = "CONFLICT"
    QUESTION = "QUESTION"
    PREDICTION = "PREDICTION"
    ALTERNATIVE = "ALTERNATIVE"
    COUNTEREXAMPLE = "COUNTEREXAMPLE"
    CAUSAL_HYPOTHESIS = "CAUSAL_HYPOTHESIS"
    TEST_PROPOSAL = "TEST_PROPOSAL"
    ACTION_PROPOSAL = "ACTION_PROPOSAL"
    VERIFICATION_REQUEST = "VERIFICATION_REQUEST"
    ESCALATION_REQUEST = "ESCALATION_REQUEST"
    LIMITATION = "LIMITATION"
    CONSTRAINT = "CONSTRAINT"
    DECISION_PROPOSAL = "DECISION_PROPOSAL"


class RelationKind(str, Enum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    DEPENDS_ON = "DEPENDS_ON"
    DERIVED_FROM = "DERIVED_FROM"
    REFINES = "REFINES"
    SUPERSEDES = "SUPERSEDES"
    TESTS = "TESTS"
    FALSIFIES = "FALSIFIES"
    PREDICTS = "PREDICTS"
    EXPLAINS = "EXPLAINS"
    CAUSES = "CAUSES"
    CORRELATES_WITH = "CORRELATES_WITH"
    ALTERNATIVE_TO = "ALTERNATIVE_TO"
    RESOLVES = "RESOLVES"
    INTRODUCES_UNCERTAINTY = "INTRODUCES_UNCERTAINTY"
    REQUIRES_EVIDENCE = "REQUIRES_EVIDENCE"
    MOTIVATES_ACTION = "MOTIVATES_ACTION"
    MOTIVATES_ESCALATION = "MOTIVATES_ESCALATION"


# Relation kinds that MUST NOT participate in a cycle -- these express a
# strict dependency/derivation order where a cycle would be a logical
# contradiction (spec section 11: "explicitly document which edge types
# may form cycles and which should not").
ACYCLIC_RELATION_KINDS = frozenset({
    RelationKind.DEPENDS_ON,
    RelationKind.DERIVED_FROM,
    RelationKind.SUPERSEDES,
})

# Relation kinds that MAY cycle (e.g. two atoms can mutually CONTRADICT or
# CORRELATE with each other; a genuine causal-feedback CAUSES loop is a
# real hypothesis shape, not an error).
CYCLE_TOLERANT_RELATION_KINDS = frozenset(
    set(RelationKind) - ACYCLIC_RELATION_KINDS
)


class SourceClass(str, Enum):
    """Trust/source classification (spec section 10) -- the single most
    important Phase 17 invariant. Every cognitive datum is one of these,
    enforced in the TYPE, never inferred from prose like "this is
    verified"."""
    MODEL_ASSERTION = "MODEL_ASSERTION"
    MEASURED_EVIDENCE_REFERENCE = "MEASURED_EVIDENCE_REFERENCE"
    EXTERNAL_EVIDENCE_REFERENCE = "EXTERNAL_EVIDENCE_REFERENCE"
    DETERMINISTIC_POLICY_REFERENCE = "DETERMINISTIC_POLICY_REFERENCE"
    HUMAN_INPUT = "HUMAN_INPUT"
    UNKNOWN = "UNKNOWN"
    DERIVED_COGNITIVE_PROPOSAL = "DERIVED_COGNITIVE_PROPOSAL"


# Only these SourceClass values may ever back a claim of measured/verified
# truth (used by the compiler's authority-impersonation checks). A
# MODEL_ASSERTION or DERIVED_COGNITIVE_PROPOSAL atom can never be flagged as
# authoritative evidence, structurally.
AUTHORITATIVE_SOURCE_CLASSES = frozenset({
    SourceClass.MEASURED_EVIDENCE_REFERENCE,
    SourceClass.EXTERNAL_EVIDENCE_REFERENCE,
    SourceClass.DETERMINISTIC_POLICY_REFERENCE,
    SourceClass.HUMAN_INPUT,
})


class ProducerKind(str, Enum):
    """Cognitive provenance (spec section 9) -- who/what produced this
    artifact/atom."""
    NATIVE_MODEL = "NATIVE_MODEL"
    EXTERNAL_PROVIDER = "EXTERNAL_PROVIDER"
    DETERMINISTIC_SYSTEM = "DETERMINISTIC_SYSTEM"
    TOOL = "TOOL"
    HUMAN = "HUMAN"
    TRANSFORMATION = "TRANSFORMATION"


class EvidenceKind(str, Enum):
    MEASURED_SYSTEM_DATA = "MEASURED_SYSTEM_DATA"
    TOOL_OUTPUT = "TOOL_OUTPUT"
    SOURCE_DOCUMENT = "SOURCE_DOCUMENT"
    CODE_TEST_EVIDENCE = "CODE_TEST_EVIDENCE"
    DETERMINISTIC_POLICY_FACT = "DETERMINISTIC_POLICY_FACT"
    VERIFICATION_RECORD = "VERIFICATION_RECORD"
    PRODUCTION_PROOF = "PRODUCTION_PROOF"
    COURT_DECISION = "COURT_DECISION"
    EXTERNAL_RETRIEVAL_RESULT = "EXTERNAL_RETRIEVAL_RESULT"
    HUMAN_SUPPLIED_ARTIFACT = "HUMAN_SUPPLIED_ARTIFACT"


class TransformationOperation(str, Enum):
    """Kinds of declared transform between one CognitiveArtifact and the
    next (spec section 13, Cognitive Conservation)."""
    CHALLENGE = "CHALLENGE"
    TEST_GENERATED = "TEST_GENERATED"
    EVIDENCE_ADDED = "EVIDENCE_ADDED"
    SUPERSEDE = "SUPERSEDE"
    FALSIFY = "FALSIFY"
    ABANDON = "ABANDON"
    INTRODUCE_ALTERNATIVE = "INTRODUCE_ALTERNATIVE"
    REMOVE_WITH_REASON = "REMOVE_WITH_REASON"
    MERGE = "MERGE"
    REFINE = "REFINE"


class ObserverView(str, Enum):
    """Named safe projections of a CognitiveArtifact (spec section 19).
    Views are DATA PROJECTIONS, never permissions."""
    MODEL_VIEW = "MODEL_VIEW"
    VERIFIER_VIEW = "VERIFIER_VIEW"
    COURT_VIEW = "COURT_VIEW"
    HUMAN_SUMMARY_VIEW = "HUMAN_SUMMARY_VIEW"
    AUDIT_VIEW = "AUDIT_VIEW"
    LEARNING_REFERENCE_VIEW = "LEARNING_REFERENCE_VIEW"
