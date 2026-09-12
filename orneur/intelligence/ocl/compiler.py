"""
The OCL Compiler/Validator (spec section 14) -- the ONLY module allowed to
accept or reject a `CognitiveArtifact`. Deterministic and model-independent:
it never decides whether a claim is TRUE, never executes anything, never
issues authority, never calls a model.

`compile_artifact()` is the single entry point: draft artifact in,
validated + canonicalized + deep-frozen artifact out, or a typed `OclError`
subclass raised. It validates EVERY top-level collection on the artifact --
atoms, relations, evidence, action_intents, verification_contracts,
escalation_requests, causal_hypotheses, counterfactual_branches -- and every
untrusted structured-data surface (all `metadata`-shaped fields), not a
subset. See PHASE17_EVIDENCE.md's closure section for the gap this closes.
"""
from __future__ import annotations

import math

from orneur.intelligence.ocl import limits
from orneur.intelligence.ocl.artifact import CognitiveArtifact
from orneur.intelligence.ocl.canonical import canonicalize, deep_freeze, to_canonical_json
from orneur.intelligence.ocl.causal import CausalHypothesis, CounterfactualBranch
from orneur.intelligence.ocl.evidence import EvidenceAnchor
from orneur.intelligence.ocl.graph import CognitiveAtom, CognitiveRelation
from orneur.intelligence.ocl.proposals import ActionIntent, EscalationRequest, VerificationContract
from orneur.intelligence.ocl.provenance import ModelIdentityRef, Provenance
from orneur.intelligence.ocl.enums import (
    ACYCLIC_RELATION_KINDS,
    AtomKind,
    EvidenceKind,
    PRIVILEGED_REFERENCE_SOURCE_CLASSES,
    ProducerKind,
    RelationKind,
    SourceClass,
)
from orneur.intelligence.ocl.trust import (
    EVIDENCE_KIND_CAPABILITY_MATRIX,
    SOURCE_CLASS_CAPABILITY_MATRIX,
    CompilationTrustContext,
    UNTRUSTED,
    is_valid_trust_context,
)
from orneur.intelligence.ocl.errors import (
    DanglingRelation,
    DuplicateActionIntentId,
    DuplicateAtomId,
    DuplicateCausalHypothesisId,
    DuplicateCounterfactualBranchId,
    DuplicateEscalationRequestId,
    DuplicateEvidenceId,
    DuplicateRelationId,
    DuplicateVerificationContractId,
    EvidenceImpersonation,
    ForbiddenAuthorityConstruct,
    GraphLimitExceeded,
    InvalidArtifactId,
    InvalidNamespace,
    InvalidObjectType,
    InvalidProvenance,
    InvalidRelationShape,
    InvalidStructuredValue,
    InvalidTrustContext,
    InvalidVerificationStatus,
    PayloadLimitExceeded,
    UnsupportedSchemaVersion,
)
from orneur.intelligence.ocl.extensions import snapshot_registry
from orneur.intelligence.ocl.typecheck import (
    require_instance,
    require_optional_int,
    require_optional_string,
    require_string,
    require_string_sequence,
    require_structured_mapping,
)
from orneur.intelligence.ocl.version import is_supported_schema_version

# Keys that must never appear (truthy) in any structured-data surface -- a
# model writing one of these is attempting to mint authority through data,
# not code (spec section 4). This is a structural, testable V1 control; it
# cannot catch the same claim phrased as free-form atom `content` text --
# see PHASE17_THREAT_MODEL.md's residual-risk note for threat #22/25.
FORBIDDEN_METADATA_KEYS = frozenset({
    "authority_granted", "verified", "policy_allows", "human_approved",
    "production_ready", "execution_grant", "authority_lease",
    "policy_decision", "human_approval", "verified_fact", "production_proof",
})

_JSON_SAFE_SCALAR_TYPES = (str, int, float, bool, type(None))


def validate_structured_value(value, *, where: str, _depth: int = 0) -> None:
    """THE single recursive validator for every untrusted structured-data
    surface (artifact/atom/relation/evidence metadata, ActionIntent
    arguments_summary, and any future metadata-like extension field).
    Recurses into dicts, lists, AND tuples (closing the nested-list
    authority-smuggling gap where only dict values were previously
    scanned) -- a forbidden key nested inside a list of dicts is caught
    just as reliably as one at the top level."""
    if _depth > limits.MAX_METADATA_DEPTH:
        raise PayloadLimitExceeded(f"{where}: structured value nesting exceeds {limits.MAX_METADATA_DEPTH}")

    if isinstance(value, dict):
        if len(value) > limits.MAX_METADATA_KEYS:
            raise PayloadLimitExceeded(f"{where}: mapping has more than {limits.MAX_METADATA_KEYS} keys")
        for key, val in value.items():
            if not isinstance(key, str):
                raise InvalidStructuredValue(f"{where}: mapping key {key!r} is not a string")
            if key in FORBIDDEN_METADATA_KEYS and val:
                raise ForbiddenAuthorityConstruct(
                    f"{where}: key {key!r} is reserved -- OCL data can never mint authority"
                )
            validate_structured_value(val, where=where, _depth=_depth + 1)
        return

    if isinstance(value, (list, tuple)):
        if len(value) > limits.MAX_METADATA_KEYS:
            raise PayloadLimitExceeded(f"{where}: sequence has more than {limits.MAX_METADATA_KEYS} elements")
        for item in value:
            validate_structured_value(item, where=where, _depth=_depth + 1)
        return

    if isinstance(value, str):
        if len(value) > limits.MAX_STRING_FIELD_LENGTH:
            raise PayloadLimitExceeded(f"{where}: string exceeds {limits.MAX_STRING_FIELD_LENGTH} chars")
        return

    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise InvalidStructuredValue(f"{where}: NaN/Infinity is not a canonicalizable value")
        return

    if isinstance(value, (int, bool)) or value is None:
        return

    raise InvalidStructuredValue(f"{where}: disallowed value type {type(value).__name__}")


def _validate_collection_element_types(draft: CognitiveArtifact) -> None:
    """Phase 17 type-parity closure section 4/8: the acceptance boundary
    must validate object SHAPE, not only field values -- a programmatic
    caller can put an int/dict/str into any top-level collection where a
    real OCL dataclass instance belongs (`atoms=(42,)`,
    `evidence=({},)`, ...). Every per-element validator below (
    `_validate_atoms`, `_validate_evidence`, etc.) assumes it already
    received the correct dataclass type; this runs FIRST, before any of
    them touch a single field, so a wrong-type element raises a typed
    `InvalidObjectType` instead of a raw `AttributeError` from the first
    attribute access."""
    for atom in draft.atoms:
        require_instance(atom, CognitiveAtom, where="artifact.atoms[]")
    for rel in draft.relations:
        require_instance(rel, CognitiveRelation, where="artifact.relations[]")
    for anchor in draft.evidence:
        require_instance(anchor, EvidenceAnchor, where="artifact.evidence[]")
    for intent in draft.action_intents:
        require_instance(intent, ActionIntent, where="artifact.action_intents[]")
    for contract in draft.verification_contracts:
        require_instance(contract, VerificationContract, where="artifact.verification_contracts[]")
    for esc in draft.escalation_requests:
        require_instance(esc, EscalationRequest, where="artifact.escalation_requests[]")
    for hyp in draft.causal_hypotheses:
        require_instance(hyp, CausalHypothesis, where="artifact.causal_hypotheses[]")
    for branch in draft.counterfactual_branches:
        require_instance(branch, CounterfactualBranch, where="artifact.counterfactual_branches[]")


def _require_id(value: str, *, where: str) -> None:
    if not value or not isinstance(value, str):
        raise InvalidArtifactId(f"{where}: id must be a non-empty string")
    if len(value) > limits.MAX_STRING_FIELD_LENGTH:
        raise PayloadLimitExceeded(f"{where}: id exceeds {limits.MAX_STRING_FIELD_LENGTH} chars")


def _validate_provenance(artifact: CognitiveArtifact) -> None:
    from orca.registry.model_spec import MODEL_SPECS, LifecycleState

    require_instance(artifact.provenance, Provenance, where="artifact.provenance")
    prov = artifact.provenance
    identity = prov.model_identity
    if identity is not None:
        require_instance(identity, ModelIdentityRef, where="provenance.model_identity")

    if not isinstance(prov.producer_kind, ProducerKind):
        raise InvalidProvenance(f"provenance.producer_kind must be a ProducerKind, got {type(prov.producer_kind).__name__}")
    require_string(prov.producer_id, where="provenance.producer_id")
    require_optional_string(prov.invocation_ref, where="provenance.invocation_ref")
    require_optional_string(prov.schema_version, where="provenance.schema_version")

    if prov.producer_kind == ProducerKind.NATIVE_MODEL:
        if identity is None or not identity.family:
            raise InvalidProvenance(
                "producer_kind=NATIVE_MODEL requires a model_identity with a family set"
            )
    if identity is not None:
        family = require_optional_string(identity.family, where="provenance.model_identity.family")
        require_optional_string(identity.lifecycle_state, where="provenance.model_identity.lifecycle_state")
        require_optional_string(identity.checkpoint_id, where="provenance.model_identity.checkpoint_id")
        require_optional_string(identity.artifact_digest, where="provenance.model_identity.artifact_digest")
        require_optional_string(identity.provider_id, where="provenance.model_identity.provider_id")
        require_optional_int(identity.generation, where="provenance.model_identity.generation")

        if family is not None and family not in MODEL_SPECS:
            raise InvalidProvenance(f"unknown model family {family!r} -- not in orca.registry.model_spec.MODEL_SPECS")
        if identity.lifecycle_state is not None:
            valid = {s.value for s in LifecycleState}
            if identity.lifecycle_state not in valid:
                raise InvalidProvenance(f"unknown lifecycle_state {identity.lifecycle_state!r}")
        if prov.producer_kind == ProducerKind.EXTERNAL_PROVIDER and family is not None:
            raise InvalidProvenance(
                "producer_kind=EXTERNAL_PROVIDER cannot claim a native model family "
                f"({family!r}) -- an external frontier response must never be "
                "relabeled as native (Phase 16 §15)."
            )


def _validate_atoms(
    artifact: CognitiveArtifact, registry_snapshot: dict, trust_context: CompilationTrustContext,
) -> dict[str, object]:
    if len(artifact.atoms) > limits.MAX_ATOMS_PER_ARTIFACT:
        raise GraphLimitExceeded(f"artifact has more than {limits.MAX_ATOMS_PER_ARTIFACT} atoms")

    by_id: dict[str, object] = {}
    for atom in artifact.atoms:
        _require_id(atom.atom_id, where="atom.atom_id")
        if atom.atom_id in by_id:
            raise DuplicateAtomId(f"duplicate atom_id {atom.atom_id!r}")
        by_id[atom.atom_id] = atom

        if not isinstance(atom.kind, AtomKind):
            raise InvalidStructuredValue(f"atom {atom.atom_id!r}.kind must be an AtomKind, got {type(atom.kind).__name__}")
        if not isinstance(atom.source_class, SourceClass):
            raise InvalidStructuredValue(f"atom {atom.atom_id!r}.source_class must be a SourceClass, got {type(atom.source_class).__name__}")

        # Type-check namespace BEFORE the registry membership lookup below --
        # an unhashable value (e.g. a list) used in `in registry_snapshot`
        # raises a raw TypeError otherwise (Phase 17 type-parity closure).
        require_string(atom.namespace, where=f"atom {atom.atom_id!r}.namespace")
        if atom.namespace not in registry_snapshot:
            raise InvalidNamespace(f"atom {atom.atom_id!r} uses unregistered namespace {atom.namespace!r}")

        require_string(atom.content, where=f"atom {atom.atom_id!r}.content")
        require_string_sequence(atom.evidence_refs, where=f"atom {atom.atom_id!r}.evidence_refs")
        require_structured_mapping(atom.metadata, where=f"atom {atom.atom_id!r}.metadata")
        validate_structured_value(atom.metadata, where=f"atom {atom.atom_id!r}.metadata")

        if atom.source_class in PRIVILEGED_REFERENCE_SOURCE_CLASSES:
            # THE root fix (Phase 17 final closure): trust is decided ONLY by
            # `trust_context`, a value the CALLER of compile_artifact() supplies
            # out-of-band -- never by anything inside `artifact` itself. A wire
            # payload that self-declares `provenance.producer_kind=
            # "DETERMINISTIC_SYSTEM"` gets ZERO extra privilege from that claim;
            # `provenance.producer_kind` remains a mere provenance CLAIM (see
            # provenance.py), not proof of trust. Capability is per-SourceClass
            # (SOURCE_CLASS_CAPABILITY_MATRIX): a TRUSTED_TOOL_ADAPTER may
            # unlock MEASURED_EVIDENCE_REFERENCE but not DETERMINISTIC_POLICY_
            # REFERENCE, and TRUSTED_HUMAN_INPUT unlocks neither.
            allowed_classes = SOURCE_CLASS_CAPABILITY_MATRIX.get(trust_context, frozenset())
            if atom.source_class not in allowed_classes:
                raise EvidenceImpersonation(
                    f"atom {atom.atom_id!r} claims privileged source_class="
                    f"{atom.source_class.value} but this compile call's trust_context "
                    f"({trust_context.value}) is not capable of unlocking it -- privileged "
                    "reference semantics require an out-of-band trusted compilation context "
                    "with the matching capability, never the artifact's own self-declared "
                    "provenance.producer_kind (spec §8: evidence must not self-authenticate)."
                )
            if atom.kind != AtomKind.OBSERVATION_REFERENCE:
                raise EvidenceImpersonation(
                    f"atom {atom.atom_id!r} has kind={atom.kind.value} but claims a privileged "
                    f"source_class={atom.source_class.value} -- only an OBSERVATION_REFERENCE atom "
                    "may claim a non-model, non-human privileged reference."
                )
            if not atom.evidence_refs:
                raise EvidenceImpersonation(
                    f"atom {atom.atom_id!r} claims source_class={atom.source_class.value} but cites "
                    "no evidence_refs -- a privileged reference claim must cite a real EvidenceAnchor."
                )

    return by_id


def _validate_evidence(artifact: CognitiveArtifact, atoms_by_id: dict, registry_snapshot: dict) -> dict[str, object]:
    evidence_by_id: dict[str, object] = {}
    for anchor in artifact.evidence:
        _require_id(anchor.evidence_id, where="evidence.evidence_id")
        if anchor.evidence_id in evidence_by_id:
            raise DuplicateEvidenceId(f"duplicate evidence_id {anchor.evidence_id!r}")
        evidence_by_id[anchor.evidence_id] = anchor
        # EvidenceKind is a str-mixin Enum: a plain string equal to a
        # member's `.value` (e.g. "COURT_DECISION") must NOT be accepted as
        # equivalent to the real enum member -- that would let a
        # programmatic caller assert an arbitrarily strong evidence kind
        # without ever going through the typed vocabulary, silently
        # bypassing the EVIDENCE_KIND_CAPABILITY_MATRIX gate downstream
        # (Phase 17 type-parity closure section 7).
        if not isinstance(anchor.evidence_kind, EvidenceKind):
            raise InvalidObjectType(
                f"evidence {anchor.evidence_id!r}.evidence_kind must be a genuine EvidenceKind "
                f"member, got {type(anchor.evidence_kind).__name__} -- a plain string matching an "
                "enum value's text is never accepted."
            )
        require_string(anchor.issuer, where=f"evidence {anchor.evidence_id!r}.issuer")
        require_string(anchor.reference, where=f"evidence {anchor.evidence_id!r}.reference")
        require_optional_string(anchor.digest, where=f"evidence {anchor.evidence_id!r}.digest")
        require_optional_string(anchor.observed_at, where=f"evidence {anchor.evidence_id!r}.observed_at")
        require_optional_string(anchor.locator, where=f"evidence {anchor.evidence_id!r}.locator")
        require_structured_mapping(anchor.metadata, where=f"evidence {anchor.evidence_id!r}.metadata")
        validate_structured_value(anchor.metadata, where=f"evidence {anchor.evidence_id!r}.metadata")

    for atom in artifact.atoms:
        for ref in atom.evidence_refs:
            if ref not in evidence_by_id:
                raise DanglingRelation(f"atom {atom.atom_id!r} references unknown evidence_id {ref!r}")
    return evidence_by_id


def _validate_evidence_kind_capability(
    artifact: CognitiveArtifact, evidence_by_id: dict, trust_context: CompilationTrustContext,
) -> None:
    """Section 7: SourceClass capability alone is not sufficient -- the
    specific EvidenceKind an atom cites must ALSO be within what this
    trust_context may certify. A TRUSTED_TOOL_ADAPTER is not equivalent to
    a Court or Policy system and must not be able to back a
    COURT_DECISION/PRODUCTION_PROOF reference merely because it is
    "trusted" in some generic sense."""
    allowed_kinds = EVIDENCE_KIND_CAPABILITY_MATRIX.get(trust_context, frozenset())
    for atom in artifact.atoms:
        if atom.source_class not in PRIVILEGED_REFERENCE_SOURCE_CLASSES:
            continue
        for ref in atom.evidence_refs:
            anchor = evidence_by_id.get(ref)
            if anchor is not None and anchor.evidence_kind not in allowed_kinds:
                raise EvidenceImpersonation(
                    f"atom {atom.atom_id!r} cites evidence {ref!r} of kind "
                    f"{anchor.evidence_kind.value}, which trust_context {trust_context.value} "
                    "is not capable of certifying -- e.g. a TRUSTED_TOOL_ADAPTER cannot back a "
                    "COURT_DECISION/PRODUCTION_PROOF reference (spec §7 evidence-kind capability)."
                )


def _validate_relations(artifact: CognitiveArtifact, atoms_by_id: dict, registry_snapshot: dict) -> None:
    if len(artifact.relations) > limits.MAX_RELATIONS_PER_ARTIFACT:
        raise GraphLimitExceeded(f"artifact has more than {limits.MAX_RELATIONS_PER_ARTIFACT} relations")

    seen_relation_ids: set[str] = set()
    acyclic_edges: dict[str, list[str]] = {}

    for rel in artifact.relations:
        _require_id(rel.relation_id, where="relation.relation_id")
        if rel.relation_id in seen_relation_ids:
            raise DuplicateRelationId(f"duplicate relation_id {rel.relation_id!r}")
        seen_relation_ids.add(rel.relation_id)

        if not isinstance(rel.kind, RelationKind):
            raise InvalidRelationShape(f"relation {rel.relation_id!r}.kind must be a RelationKind, got {type(rel.kind).__name__}")

        # Type-check namespace BEFORE the registry membership lookup below,
        # same rationale as `_validate_atoms` (Phase 17 type-parity closure).
        require_string(rel.namespace, where=f"relation {rel.relation_id!r}.namespace")
        if rel.namespace not in registry_snapshot:
            raise InvalidNamespace(f"relation {rel.relation_id!r} uses unregistered namespace {rel.namespace!r}")
        require_structured_mapping(rel.metadata, where=f"relation {rel.relation_id!r}.metadata")
        validate_structured_value(rel.metadata, where=f"relation {rel.relation_id!r}.metadata")
        require_string(rel.source_atom_id, where=f"relation {rel.relation_id!r}.source_atom_id")
        require_string(rel.target_atom_id, where=f"relation {rel.relation_id!r}.target_atom_id")
        if rel.source_atom_id not in atoms_by_id:
            raise DanglingRelation(f"relation {rel.relation_id!r} source_atom_id {rel.source_atom_id!r} does not exist")
        if rel.target_atom_id not in atoms_by_id:
            raise DanglingRelation(f"relation {rel.relation_id!r} target_atom_id {rel.target_atom_id!r} does not exist")

        if rel.kind in ACYCLIC_RELATION_KINDS:
            if rel.source_atom_id == rel.target_atom_id:
                raise InvalidRelationShape(
                    f"relation {rel.relation_id!r} of acyclic kind {rel.kind.value} cannot self-reference"
                )
            acyclic_edges.setdefault(rel.source_atom_id, []).append(rel.target_atom_id)

    _detect_cycle(acyclic_edges)


def _detect_cycle(edges: dict[str, list[str]]) -> None:
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {}

    def visit(node: str) -> None:
        color[node] = GRAY
        for nxt in edges.get(node, ()):
            state = color.get(nxt, WHITE)
            if state == GRAY:
                raise InvalidRelationShape(
                    f"acyclic-kind relation graph contains a cycle involving {node!r} -> {nxt!r}"
                )
            if state == WHITE:
                visit(nxt)
        color[node] = BLACK

    for node in list(edges.keys()):
        if color.get(node, WHITE) == WHITE:
            visit(node)


def _atom_kind_or_none(atoms_by_id: dict, atom_id: str):
    atom = atoms_by_id.get(atom_id)
    return atom.kind if atom is not None else None


def _validate_action_intents(artifact: CognitiveArtifact, atoms_by_id: dict, contract_ids: set[str]) -> None:
    seen: set[str] = set()
    for intent in artifact.action_intents:
        _require_id(intent.intent_id, where="action_intent.intent_id")
        if intent.intent_id in seen:
            raise DuplicateActionIntentId(f"duplicate intent_id {intent.intent_id!r}")
        seen.add(intent.intent_id)

        require_string(intent.proposed_capability, where=f"action_intent {intent.intent_id!r}.proposed_capability")
        require_optional_string(intent.target_reference, where=f"action_intent {intent.intent_id!r}.target_reference")
        require_string(intent.expected_effect, where=f"action_intent {intent.intent_id!r}.expected_effect")
        require_structured_mapping(intent.arguments_summary, where=f"action_intent {intent.intent_id!r}.arguments_summary")
        validate_structured_value(intent.arguments_summary, where=f"action_intent {intent.intent_id!r}.arguments_summary")
        require_string_sequence(intent.preconditions, where=f"action_intent {intent.intent_id!r}.preconditions")
        require_string_sequence(intent.risk_hints, where=f"action_intent {intent.intent_id!r}.risk_hints")
        require_string_sequence(intent.rationale_atom_refs, where=f"action_intent {intent.intent_id!r}.rationale_atom_refs")
        require_string_sequence(intent.verification_requirement_refs, where=f"action_intent {intent.intent_id!r}.verification_requirement_refs")

        for ref in intent.rationale_atom_refs:
            if ref not in atoms_by_id:
                raise DanglingRelation(f"action_intent {intent.intent_id!r} rationale_atom_refs references unknown atom_id {ref!r}")
        for ref in intent.verification_requirement_refs:
            if ref not in contract_ids:
                raise DanglingRelation(f"action_intent {intent.intent_id!r} verification_requirement_refs references unknown contract_id {ref!r}")


def _validate_verification_contracts(artifact: CognitiveArtifact, atoms_by_id: dict) -> set[str]:
    seen: set[str] = set()
    for contract in artifact.verification_contracts:
        _require_id(contract.contract_id, where="verification_contract.contract_id")
        if contract.contract_id in seen:
            raise DuplicateVerificationContractId(f"duplicate contract_id {contract.contract_id!r}")
        seen.add(contract.contract_id)

        require_string(contract.target_atom_ref, where=f"verification_contract {contract.contract_id!r}.target_atom_ref")
        if contract.target_atom_ref not in atoms_by_id:
            raise DanglingRelation(f"verification_contract {contract.contract_id!r} target_atom_ref {contract.target_atom_ref!r} does not exist")
        require_string(contract.status, where=f"verification_contract {contract.contract_id!r}.status")
        if contract.status != "UNRESOLVED":
            raise InvalidVerificationStatus(
                f"verification_contract {contract.contract_id!r} has status={contract.status!r} -- "
                "OCL V1 does not permit any status other than the literal string 'UNRESOLVED'. A "
                "VerificationContract is a REQUEST, never the VerificationRecord itself; only the "
                "real Phase 15 verification path may ever record a pass/fail outcome."
            )
        require_string(contract.proposed_test, where=f"verification_contract {contract.contract_id!r}.proposed_test")
        require_string_sequence(contract.required_evidence_kinds, where=f"verification_contract {contract.contract_id!r}.required_evidence_kinds")
        require_string_sequence(contract.pass_conditions, where=f"verification_contract {contract.contract_id!r}.pass_conditions")
        require_string_sequence(contract.fail_conditions, where=f"verification_contract {contract.contract_id!r}.fail_conditions")
        require_optional_string(contract.verification_scope_ref, where=f"verification_contract {contract.contract_id!r}.verification_scope_ref")
    return seen


def _validate_escalation_requests(artifact: CognitiveArtifact, atoms_by_id: dict) -> None:
    seen: set[str] = set()
    for esc in artifact.escalation_requests:
        _require_id(esc.escalation_id, where="escalation_request.escalation_id")
        if esc.escalation_id in seen:
            raise DuplicateEscalationRequestId(f"duplicate escalation_id {esc.escalation_id!r}")
        seen.add(esc.escalation_id)

        require_string(esc.evidence_deficit, where=f"escalation_request {esc.escalation_id!r}.evidence_deficit")
        require_string(esc.requested_capability_type, where=f"escalation_request {esc.escalation_id!r}.requested_capability_type")
        require_optional_string(esc.requested_cognitive_role, where=f"escalation_request {esc.escalation_id!r}.requested_cognitive_role")
        require_string_sequence(esc.reason_categories, where=f"escalation_request {esc.escalation_id!r}.reason_categories")
        require_string_sequence(esc.triggering_atom_refs, where=f"escalation_request {esc.escalation_id!r}.triggering_atom_refs")
        require_string_sequence(esc.unresolved_conflict_refs, where=f"escalation_request {esc.escalation_id!r}.unresolved_conflict_refs")
        for ref in esc.triggering_atom_refs:
            if ref not in atoms_by_id:
                raise DanglingRelation(f"escalation_request {esc.escalation_id!r} triggering_atom_refs references unknown atom_id {ref!r}")
        for ref in esc.unresolved_conflict_refs:
            if ref not in atoms_by_id:
                raise DanglingRelation(f"escalation_request {esc.escalation_id!r} unresolved_conflict_refs references unknown atom_id {ref!r}")
            if _atom_kind_or_none(atoms_by_id, ref) != AtomKind.CONFLICT:
                raise InvalidRelationShape(
                    f"escalation_request {esc.escalation_id!r} unresolved_conflict_refs entry {ref!r} is not a CONFLICT atom"
                )


def _validate_causal_hypotheses(artifact: CognitiveArtifact, atoms_by_id: dict) -> set[str]:
    seen: set[str] = set()
    for hyp in artifact.causal_hypotheses:
        _require_id(hyp.hypothesis_id, where="causal_hypothesis.hypothesis_id")
        if hyp.hypothesis_id in seen:
            raise DuplicateCausalHypothesisId(f"duplicate hypothesis_id {hyp.hypothesis_id!r}")
        seen.add(hyp.hypothesis_id)

        require_string(hyp.mechanism, where=f"causal_hypothesis {hyp.hypothesis_id!r}.mechanism")
        require_string(hyp.cause_atom_ref, where=f"causal_hypothesis {hyp.hypothesis_id!r}.cause_atom_ref")
        require_string(hyp.predicted_consequence_atom_ref, where=f"causal_hypothesis {hyp.hypothesis_id!r}.predicted_consequence_atom_ref")
        require_optional_string(hyp.observable_test_ref, where=f"causal_hypothesis {hyp.hypothesis_id!r}.observable_test_ref")
        require_string_sequence(hyp.observed_evidence_refs, where=f"causal_hypothesis {hyp.hypothesis_id!r}.observed_evidence_refs")
        if hyp.cause_atom_ref not in atoms_by_id:
            raise DanglingRelation(f"causal_hypothesis {hyp.hypothesis_id!r} cause_atom_ref {hyp.cause_atom_ref!r} does not exist")
        if hyp.predicted_consequence_atom_ref not in atoms_by_id:
            raise DanglingRelation(f"causal_hypothesis {hyp.hypothesis_id!r} predicted_consequence_atom_ref {hyp.predicted_consequence_atom_ref!r} does not exist")
        if hyp.observable_test_ref is not None:
            if hyp.observable_test_ref not in atoms_by_id:
                raise DanglingRelation(f"causal_hypothesis {hyp.hypothesis_id!r} observable_test_ref {hyp.observable_test_ref!r} does not exist")
            if _atom_kind_or_none(atoms_by_id, hyp.observable_test_ref) != AtomKind.TEST_PROPOSAL:
                raise InvalidRelationShape(
                    f"causal_hypothesis {hyp.hypothesis_id!r} observable_test_ref {hyp.observable_test_ref!r} "
                    "is not a TEST_PROPOSAL atom -- observable_test_ref must resolve to the atom "
                    "describing the proposed test, not an arbitrary reference."
                )
        for ref in hyp.observed_evidence_refs:
            if ref not in {e.evidence_id for e in artifact.evidence}:
                raise DanglingRelation(f"causal_hypothesis {hyp.hypothesis_id!r} observed_evidence_refs references unknown evidence_id {ref!r}")
    return seen


def _validate_counterfactual_branches(artifact: CognitiveArtifact, atoms_by_id: dict, hypothesis_ids: set[str]) -> None:
    seen: set[str] = set()
    for branch in artifact.counterfactual_branches:
        _require_id(branch.branch_id, where="counterfactual_branch.branch_id")
        if branch.branch_id in seen:
            raise DuplicateCounterfactualBranchId(f"duplicate branch_id {branch.branch_id!r}")
        seen.add(branch.branch_id)

        require_string(branch.causal_hypothesis_ref, where=f"counterfactual_branch {branch.branch_id!r}.causal_hypothesis_ref")
        require_string(branch.condition_atom_ref, where=f"counterfactual_branch {branch.branch_id!r}.condition_atom_ref")
        require_string(branch.predicted_atom_ref, where=f"counterfactual_branch {branch.branch_id!r}.predicted_atom_ref")
        if branch.causal_hypothesis_ref not in hypothesis_ids:
            raise DanglingRelation(f"counterfactual_branch {branch.branch_id!r} causal_hypothesis_ref {branch.causal_hypothesis_ref!r} does not exist")
        if branch.condition_atom_ref not in atoms_by_id:
            raise DanglingRelation(f"counterfactual_branch {branch.branch_id!r} condition_atom_ref {branch.condition_atom_ref!r} does not exist")
        if branch.predicted_atom_ref not in atoms_by_id:
            raise DanglingRelation(f"counterfactual_branch {branch.branch_id!r} predicted_atom_ref {branch.predicted_atom_ref!r} does not exist")


def compile_artifact(
    draft: CognitiveArtifact, *, trust_context: CompilationTrustContext = UNTRUSTED,
) -> CognitiveArtifact:
    """Validate `draft` and return a canonicalized, deeply-immutable
    `CognitiveArtifact`. Raises a typed `OclError` subclass on any
    violation; never partially accepts an invalid artifact. Validates
    EVERY top-level collection -- this is the single acceptance boundary,
    not a subset of one.

    `trust_context` MUST be supplied by the CALLER, established out-of-band
    -- never parsed from `draft` itself. Defaults to `UNTRUSTED_MODEL_OR_WIRE`
    (the safe default): only a caller who has independently verified a
    draft's true origin should pass a stronger `CompilationTrustContext`
    explicitly (see trust.py). `trust_context` MUST be a genuine
    `CompilationTrustContext` enum member -- a plain string equal to one of
    its values is REJECTED (`InvalidTrustContext`), even though `str`-mixin
    `Enum` equality would otherwise let it slip through a naive membership
    check."""
    if not is_valid_trust_context(trust_context):
        raise InvalidTrustContext(
            f"trust_context must be a genuine CompilationTrustContext member, got "
            f"{type(trust_context).__name__} {trust_context!r} -- a plain string is never accepted "
            "even if it matches an enum value's text."
        )

    # Run BEFORE anything else touches a single field of a collection
    # element -- a wrong-type element (e.g. `atoms=(42,)`) must raise a
    # typed InvalidObjectType, not a raw AttributeError from whichever
    # validator happens to read `.atom_id`/`.relation_id`/etc first
    # (Phase 17 type-parity closure sections 2F/4/8).
    _validate_collection_element_types(draft)

    _require_id(draft.artifact_id, where="artifact.artifact_id")
    _require_id(draft.request_id, where="artifact.request_id")
    if draft.parent_artifact_id is not None:
        _require_id(draft.parent_artifact_id, where="artifact.parent_artifact_id")
    if draft.transformation_id is not None:
        _require_id(draft.transformation_id, where="artifact.transformation_id")
    require_string(draft.schema_version, where="artifact.schema_version")
    require_string(draft.created_at, where="artifact.created_at")
    if not is_supported_schema_version(draft.schema_version):
        raise UnsupportedSchemaVersion(
            f"schema_version {draft.schema_version!r} is not supported by this build"
        )

    require_structured_mapping(draft.metadata, where="artifact.metadata")
    validate_structured_value(draft.metadata, where="artifact.metadata")

    registry_snapshot = snapshot_registry()

    atoms_by_id = _validate_atoms(draft, registry_snapshot, trust_context)
    evidence_by_id = _validate_evidence(draft, atoms_by_id, registry_snapshot)
    _validate_evidence_kind_capability(draft, evidence_by_id, trust_context)
    _validate_relations(draft, atoms_by_id, registry_snapshot)
    _validate_provenance(draft)

    contract_ids = _validate_verification_contracts(draft, atoms_by_id)
    _validate_action_intents(draft, atoms_by_id, contract_ids)
    _validate_escalation_requests(draft, atoms_by_id)
    hypothesis_ids = _validate_causal_hypotheses(draft, atoms_by_id)
    _validate_counterfactual_branches(draft, atoms_by_id, hypothesis_ids)

    require_string_sequence(draft.limitation_atom_refs, where="artifact.limitation_atom_refs")
    for ref in draft.limitation_atom_refs:
        if ref not in atoms_by_id:
            raise DanglingRelation(f"limitation_atom_refs references unknown atom_id {ref!r}")
        if atoms_by_id[ref].kind != AtomKind.LIMITATION:
            raise InvalidRelationShape(f"limitation_atom_refs entry {ref!r} is not a LIMITATION atom")

    canonical = canonicalize(draft)

    serialized_size = len(to_canonical_json(canonical).encode("utf-8"))
    if serialized_size > limits.MAX_ARTIFACT_SERIALIZED_BYTES:
        raise PayloadLimitExceeded(
            f"canonical artifact serializes to {serialized_size} bytes, exceeding "
            f"MAX_ARTIFACT_SERIALIZED_BYTES={limits.MAX_ARTIFACT_SERIALIZED_BYTES}"
        )

    return deep_freeze(canonical)
