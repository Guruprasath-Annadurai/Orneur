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
from orneur.intelligence.ocl.enums import (
    ACYCLIC_RELATION_KINDS,
    AtomKind,
    AUTHORITATIVE_SOURCE_CLASSES,
    ProducerKind,
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
    InvalidProvenance,
    InvalidRelationShape,
    InvalidStructuredValue,
    InvalidVerificationStatus,
    PayloadLimitExceeded,
    UnsupportedSchemaVersion,
)
from orneur.intelligence.ocl.extensions import snapshot_registry
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

# Provenance kinds an untrusted (model-controlled) artifact's OWN top-level
# producer may have. An artifact produced by one of these can never contain
# an atom claiming an AUTHORITATIVE_SOURCE_CLASSES value -- a model/external
# provider cannot self-authenticate its own evidence merely by constructing
# the wire payload (spec section 8: "evidence must not self-authenticate").
_UNTRUSTED_ARTIFACT_PRODUCER_KINDS = frozenset({ProducerKind.NATIVE_MODEL, ProducerKind.EXTERNAL_PROVIDER})

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


def _check_string_limits(value: str, *, where: str) -> None:
    if len(value) > limits.MAX_STRING_FIELD_LENGTH:
        raise PayloadLimitExceeded(f"{where}: string field exceeds {limits.MAX_STRING_FIELD_LENGTH} chars")


def _require_id(value: str, *, where: str) -> None:
    if not value or not isinstance(value, str):
        raise InvalidArtifactId(f"{where}: id must be a non-empty string")
    if len(value) > limits.MAX_STRING_FIELD_LENGTH:
        raise PayloadLimitExceeded(f"{where}: id exceeds {limits.MAX_STRING_FIELD_LENGTH} chars")


def _validate_provenance(artifact: CognitiveArtifact) -> None:
    from orca.registry.model_spec import MODEL_SPECS, LifecycleState

    prov = artifact.provenance
    identity = prov.model_identity

    if prov.producer_kind == ProducerKind.NATIVE_MODEL:
        if identity is None or not identity.family:
            raise InvalidProvenance(
                "producer_kind=NATIVE_MODEL requires a model_identity with a family set"
            )
    if identity is not None:
        if identity.family is not None and identity.family not in MODEL_SPECS:
            raise InvalidProvenance(f"unknown model family {identity.family!r} -- not in orca.registry.model_spec.MODEL_SPECS")
        if identity.lifecycle_state is not None:
            valid = {s.value for s in LifecycleState}
            if identity.lifecycle_state not in valid:
                raise InvalidProvenance(f"unknown lifecycle_state {identity.lifecycle_state!r}")
        if prov.producer_kind == ProducerKind.EXTERNAL_PROVIDER and identity.family is not None:
            raise InvalidProvenance(
                "producer_kind=EXTERNAL_PROVIDER cannot claim a native model family "
                f"({identity.family!r}) -- an external frontier response must never be "
                "relabeled as native (Phase 16 §15)."
            )


def _validate_atoms(artifact: CognitiveArtifact, registry_snapshot: dict) -> dict[str, object]:
    if len(artifact.atoms) > limits.MAX_ATOMS_PER_ARTIFACT:
        raise GraphLimitExceeded(f"artifact has more than {limits.MAX_ATOMS_PER_ARTIFACT} atoms")

    untrusted_artifact = artifact.provenance.producer_kind in _UNTRUSTED_ARTIFACT_PRODUCER_KINDS

    by_id: dict[str, object] = {}
    for atom in artifact.atoms:
        _require_id(atom.atom_id, where="atom.atom_id")
        if atom.atom_id in by_id:
            raise DuplicateAtomId(f"duplicate atom_id {atom.atom_id!r}")
        by_id[atom.atom_id] = atom

        if atom.namespace not in registry_snapshot:
            raise InvalidNamespace(f"atom {atom.atom_id!r} uses unregistered namespace {atom.namespace!r}")

        _check_string_limits(atom.content, where=f"atom {atom.atom_id!r}.content")
        validate_structured_value(atom.metadata, where=f"atom {atom.atom_id!r}.metadata")

        if atom.source_class in AUTHORITATIVE_SOURCE_CLASSES:
            if untrusted_artifact:
                raise EvidenceImpersonation(
                    f"atom {atom.atom_id!r} claims authoritative source_class="
                    f"{atom.source_class.value} inside an artifact produced by "
                    f"{artifact.provenance.producer_kind.value} -- a model/external-provider-"
                    "produced artifact can never self-authenticate its own evidence (spec §8: "
                    "evidence must not self-authenticate)."
                )
            if atom.kind != AtomKind.OBSERVATION_REFERENCE:
                raise EvidenceImpersonation(
                    f"atom {atom.atom_id!r} has kind={atom.kind.value} but claims an authoritative "
                    f"source_class={atom.source_class.value} -- only an OBSERVATION_REFERENCE atom "
                    "may claim a non-model, non-human authoritative source."
                )
            if not atom.evidence_refs:
                raise EvidenceImpersonation(
                    f"atom {atom.atom_id!r} claims source_class={atom.source_class.value} but cites "
                    "no evidence_refs -- an authoritative claim must reference a real EvidenceAnchor."
                )

    return by_id


def _validate_evidence(artifact: CognitiveArtifact, atoms_by_id: dict, registry_snapshot: dict) -> set[str]:
    evidence_ids: set[str] = set()
    for anchor in artifact.evidence:
        _require_id(anchor.evidence_id, where="evidence.evidence_id")
        if anchor.evidence_id in evidence_ids:
            raise DuplicateEvidenceId(f"duplicate evidence_id {anchor.evidence_id!r}")
        evidence_ids.add(anchor.evidence_id)
        _check_string_limits(anchor.reference, where=f"evidence {anchor.evidence_id!r}.reference")
        validate_structured_value(anchor.metadata, where=f"evidence {anchor.evidence_id!r}.metadata")

    for atom in artifact.atoms:
        for ref in atom.evidence_refs:
            if ref not in evidence_ids:
                raise DanglingRelation(f"atom {atom.atom_id!r} references unknown evidence_id {ref!r}")
    return evidence_ids


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

        if rel.namespace not in registry_snapshot:
            raise InvalidNamespace(f"relation {rel.relation_id!r} uses unregistered namespace {rel.namespace!r}")
        validate_structured_value(rel.metadata, where=f"relation {rel.relation_id!r}.metadata")
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

        _check_string_limits(intent.proposed_capability, where=f"action_intent {intent.intent_id!r}.proposed_capability")
        _check_string_limits(intent.expected_effect, where=f"action_intent {intent.intent_id!r}.expected_effect")
        validate_structured_value(intent.arguments_summary, where=f"action_intent {intent.intent_id!r}.arguments_summary")

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

        if contract.target_atom_ref not in atoms_by_id:
            raise DanglingRelation(f"verification_contract {contract.contract_id!r} target_atom_ref {contract.target_atom_ref!r} does not exist")
        if contract.status != "UNRESOLVED":
            raise InvalidVerificationStatus(
                f"verification_contract {contract.contract_id!r} has status={contract.status!r} -- "
                "OCL V1 does not permit any status other than the literal string 'UNRESOLVED'. A "
                "VerificationContract is a REQUEST, never the VerificationRecord itself; only the "
                "real Phase 15 verification path may ever record a pass/fail outcome."
            )
        _check_string_limits(contract.proposed_test, where=f"verification_contract {contract.contract_id!r}.proposed_test")
    return seen


def _validate_escalation_requests(artifact: CognitiveArtifact, atoms_by_id: dict) -> None:
    seen: set[str] = set()
    for esc in artifact.escalation_requests:
        _require_id(esc.escalation_id, where="escalation_request.escalation_id")
        if esc.escalation_id in seen:
            raise DuplicateEscalationRequestId(f"duplicate escalation_id {esc.escalation_id!r}")
        seen.add(esc.escalation_id)

        _check_string_limits(esc.evidence_deficit, where=f"escalation_request {esc.escalation_id!r}.evidence_deficit")
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

        _check_string_limits(hyp.mechanism, where=f"causal_hypothesis {hyp.hypothesis_id!r}.mechanism")
        if hyp.cause_atom_ref not in atoms_by_id:
            raise DanglingRelation(f"causal_hypothesis {hyp.hypothesis_id!r} cause_atom_ref {hyp.cause_atom_ref!r} does not exist")
        if hyp.predicted_consequence_atom_ref not in atoms_by_id:
            raise DanglingRelation(f"causal_hypothesis {hyp.hypothesis_id!r} predicted_consequence_atom_ref {hyp.predicted_consequence_atom_ref!r} does not exist")
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

        if branch.causal_hypothesis_ref not in hypothesis_ids:
            raise DanglingRelation(f"counterfactual_branch {branch.branch_id!r} causal_hypothesis_ref {branch.causal_hypothesis_ref!r} does not exist")
        if branch.condition_atom_ref not in atoms_by_id:
            raise DanglingRelation(f"counterfactual_branch {branch.branch_id!r} condition_atom_ref {branch.condition_atom_ref!r} does not exist")
        if branch.predicted_atom_ref not in atoms_by_id:
            raise DanglingRelation(f"counterfactual_branch {branch.branch_id!r} predicted_atom_ref {branch.predicted_atom_ref!r} does not exist")


def compile_artifact(draft: CognitiveArtifact) -> CognitiveArtifact:
    """Validate `draft` and return a canonicalized, deeply-immutable
    `CognitiveArtifact`. Raises a typed `OclError` subclass on any
    violation; never partially accepts an invalid artifact. Validates
    EVERY top-level collection -- this is the single acceptance boundary,
    not a subset of one."""
    _require_id(draft.artifact_id, where="artifact.artifact_id")
    if not is_supported_schema_version(draft.schema_version):
        raise UnsupportedSchemaVersion(
            f"schema_version {draft.schema_version!r} is not supported by this build"
        )

    validate_structured_value(draft.metadata, where="artifact.metadata")

    registry_snapshot = snapshot_registry()

    atoms_by_id = _validate_atoms(draft, registry_snapshot)
    _validate_evidence(draft, atoms_by_id, registry_snapshot)
    _validate_relations(draft, atoms_by_id, registry_snapshot)
    _validate_provenance(draft)

    contract_ids = _validate_verification_contracts(draft, atoms_by_id)
    _validate_action_intents(draft, atoms_by_id, contract_ids)
    _validate_escalation_requests(draft, atoms_by_id)
    hypothesis_ids = _validate_causal_hypotheses(draft, atoms_by_id)
    _validate_counterfactual_branches(draft, atoms_by_id, hypothesis_ids)

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
