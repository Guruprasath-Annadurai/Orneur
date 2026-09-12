"""
The OCL Compiler/Validator (spec section 14) -- the ONLY module allowed to
accept or reject a `CognitiveArtifact`. Deterministic and model-independent:
it never decides whether a claim is TRUE, never executes anything, never
issues authority, never calls a model.

`compile_artifact()` is the single entry point: draft artifact in,
validated + canonicalized artifact out, or a typed `OclError` subclass
raised.
"""
from __future__ import annotations

from orneur.intelligence.ocl import limits
from orneur.intelligence.ocl.artifact import CognitiveArtifact
from orneur.intelligence.ocl.canonical import canonicalize
from orneur.intelligence.ocl.enums import AtomKind, ProducerKind, SourceClass, ACYCLIC_RELATION_KINDS
from orneur.intelligence.ocl.errors import (
    DanglingRelation,
    DuplicateAtomId,
    EvidenceImpersonation,
    ForbiddenAuthorityConstruct,
    GraphLimitExceeded,
    InvalidArtifactId,
    InvalidNamespace,
    InvalidProvenance,
    InvalidRelationShape,
    PayloadLimitExceeded,
    UnsupportedSchemaVersion,
)
from orneur.intelligence.ocl.extensions import is_registered_namespace
from orneur.intelligence.ocl.version import is_supported_schema_version

# Keys that must never appear (truthy) in artifact/atom metadata -- a model
# writing one of these is attempting to mint authority through data, not
# code (spec section 4). This is a structural, testable V1 control; it
# cannot catch the same claim phrased as free-form atom `content` text --
# see PHASE17_THREAT_MODEL.md's residual-risk note for threat #22/25.
FORBIDDEN_METADATA_KEYS = frozenset({
    "authority_granted", "verified", "policy_allows", "human_approved",
    "production_ready", "execution_grant", "authority_lease",
    "policy_decision", "human_approval", "verified_fact", "production_proof",
})

_AUTHORITATIVE_SOURCE_CLASSES = frozenset({
    SourceClass.MEASURED_EVIDENCE_REFERENCE,
    SourceClass.EXTERNAL_EVIDENCE_REFERENCE,
    SourceClass.DETERMINISTIC_POLICY_REFERENCE,
})


def _check_forbidden_metadata(metadata: dict, *, where: str, _depth: int = 0) -> None:
    if _depth > limits.MAX_METADATA_DEPTH:
        raise PayloadLimitExceeded(f"{where}: metadata nesting exceeds {limits.MAX_METADATA_DEPTH}")
    if len(metadata) > limits.MAX_METADATA_KEYS:
        raise PayloadLimitExceeded(f"{where}: metadata has more than {limits.MAX_METADATA_KEYS} keys")
    for key, value in metadata.items():
        if key in FORBIDDEN_METADATA_KEYS and value:
            raise ForbiddenAuthorityConstruct(
                f"{where}: metadata key {key!r} is reserved -- OCL data can never mint authority"
            )
        if isinstance(value, dict):
            _check_forbidden_metadata(value, where=where, _depth=_depth + 1)


def _check_string_limits(value: str, *, where: str) -> None:
    if len(value) > limits.MAX_STRING_FIELD_LENGTH:
        raise PayloadLimitExceeded(f"{where}: string field exceeds {limits.MAX_STRING_FIELD_LENGTH} chars")


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


def _validate_atoms(artifact: CognitiveArtifact) -> dict[str, "CognitiveAtom"]:
    if len(artifact.atoms) > limits.MAX_ATOMS_PER_ARTIFACT:
        raise GraphLimitExceeded(f"artifact has more than {limits.MAX_ATOMS_PER_ARTIFACT} atoms")

    by_id: dict[str, object] = {}
    for atom in artifact.atoms:
        if not atom.atom_id:
            raise InvalidArtifactId("atom_id must be non-empty")
        if atom.atom_id in by_id:
            raise DuplicateAtomId(f"duplicate atom_id {atom.atom_id!r}")
        by_id[atom.atom_id] = atom

        if not is_registered_namespace(atom.namespace):
            raise InvalidNamespace(f"atom {atom.atom_id!r} uses unregistered namespace {atom.namespace!r}")

        _check_string_limits(atom.content, where=f"atom {atom.atom_id!r}.content")
        _check_forbidden_metadata(atom.metadata, where=f"atom {atom.atom_id!r}")

        if atom.source_class in _AUTHORITATIVE_SOURCE_CLASSES:
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


def _validate_evidence(artifact: CognitiveArtifact, atoms_by_id: dict) -> set[str]:
    evidence_ids: set[str] = set()
    for anchor in artifact.evidence:
        if anchor.evidence_id in evidence_ids:
            raise DuplicateAtomId(f"duplicate evidence_id {anchor.evidence_id!r}")
        evidence_ids.add(anchor.evidence_id)

    for atom in artifact.atoms:
        for ref in atom.evidence_refs:
            if ref not in evidence_ids:
                raise DanglingRelation(f"atom {atom.atom_id!r} references unknown evidence_id {ref!r}")
    return evidence_ids


def _validate_relations(artifact: CognitiveArtifact, atoms_by_id: dict) -> None:
    if len(artifact.relations) > limits.MAX_RELATIONS_PER_ARTIFACT:
        raise GraphLimitExceeded(f"artifact has more than {limits.MAX_RELATIONS_PER_ARTIFACT} relations")

    seen_relation_ids: set[str] = set()
    acyclic_edges: dict[str, list[str]] = {}

    for rel in artifact.relations:
        if rel.relation_id in seen_relation_ids:
            raise DuplicateAtomId(f"duplicate relation_id {rel.relation_id!r}")
        seen_relation_ids.add(rel.relation_id)

        if not is_registered_namespace(rel.namespace):
            raise InvalidNamespace(f"relation {rel.relation_id!r} uses unregistered namespace {rel.namespace!r}")
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


def compile_artifact(draft: CognitiveArtifact) -> CognitiveArtifact:
    """Validate `draft` and return a canonicalized, immutable
    `CognitiveArtifact`. Raises a typed `OclError` subclass on any
    violation; never partially accepts an invalid artifact."""
    if not draft.artifact_id:
        raise InvalidArtifactId("artifact_id must be non-empty")
    if not is_supported_schema_version(draft.schema_version):
        raise UnsupportedSchemaVersion(
            f"schema_version {draft.schema_version!r} is not supported by this build"
        )

    _check_forbidden_metadata(draft.metadata, where="artifact")

    atoms_by_id = _validate_atoms(draft)
    _validate_evidence(draft, atoms_by_id)
    _validate_relations(draft, atoms_by_id)
    _validate_provenance(draft)

    for ref in draft.limitation_atom_refs:
        if ref not in atoms_by_id:
            raise DanglingRelation(f"limitation_atom_refs references unknown atom_id {ref!r}")
        if atoms_by_id[ref].kind != AtomKind.LIMITATION:
            raise InvalidRelationShape(f"limitation_atom_refs entry {ref!r} is not a LIMITATION atom")

    canonical = canonicalize(draft)

    from orneur.intelligence.ocl.canonical import to_canonical_json
    serialized_size = len(to_canonical_json(canonical).encode("utf-8"))
    if serialized_size > limits.MAX_ARTIFACT_SERIALIZED_BYTES:
        raise PayloadLimitExceeded(
            f"canonical artifact serializes to {serialized_size} bytes, exceeding "
            f"MAX_ARTIFACT_SERIALIZED_BYTES={limits.MAX_ARTIFACT_SERIALIZED_BYTES}"
        )

    return canonical
