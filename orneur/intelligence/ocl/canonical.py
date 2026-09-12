"""
Canonicalization, deep immutability, content digest, and wire (de)
serialization (spec sections 15, 23, 24, 25; Phase 17 closure sections 5-7).

`canonicalize(artifact)` returns a NEW `CognitiveArtifact` whose
collections are sorted into a stable, deterministic order. `deep_freeze()`
then converts every nested mapping into a `MappingProxyType` over a FRESH
copy (never the caller's own dict) and every list into a tuple, recursively
-- so a compiled artifact holds no mutable, aliasable container anywhere,
closing both the "mutate after hash" and "caller-owned-dict alias mutation"
gaps. `digest(artifact)` returns a SHA-256 hex digest of the canonical JSON
form -- stdlib crypto only, no custom scheme, and no claim of cryptographic
authentication (a digest proves content identity, not who produced it or
that it wasn't tampered with in transit; that is a separate, unimplemented
signing concern).

Wire parsing is STRICT (section 6): `parse_ocl_draft_json()` rejects
duplicate JSON object keys and unknown fields at every level, and converts
missing/malformed data into typed `OclError` subclasses rather than a raw
`KeyError`/`ValueError`. It returns an UNVALIDATED draft -- callers that
want a trusted artifact MUST call `compiler.compile_artifact()` on the
result (or use `checkpoint.restore_checkpoint()`, which already does this).
There is no function in this module whose name suggests safety while
skipping compilation.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from enum import Enum
from types import MappingProxyType

from orneur.intelligence.ocl.artifact import CognitiveArtifact
from orneur.intelligence.ocl.errors import (
    DuplicateWireKey,
    InvalidCanonicalForm,
    MalformedWireShape,
    MissingMandatoryField,
    UnknownWireField,
)


def canonicalize(artifact: CognitiveArtifact) -> CognitiveArtifact:
    return dataclasses.replace(
        artifact,
        atoms=tuple(sorted(artifact.atoms, key=lambda a: a.atom_id)),
        relations=tuple(sorted(artifact.relations, key=lambda r: r.relation_id)),
        evidence=tuple(sorted(artifact.evidence, key=lambda e: e.evidence_id)),
        action_intents=tuple(sorted(artifact.action_intents, key=lambda x: x.intent_id)),
        verification_contracts=tuple(sorted(artifact.verification_contracts, key=lambda x: x.contract_id)),
        escalation_requests=tuple(sorted(artifact.escalation_requests, key=lambda x: x.escalation_id)),
        causal_hypotheses=tuple(sorted(artifact.causal_hypotheses, key=lambda x: x.hypothesis_id)),
        counterfactual_branches=tuple(sorted(artifact.counterfactual_branches, key=lambda x: x.branch_id)),
        limitation_atom_refs=tuple(sorted(artifact.limitation_atom_refs)),
    )


def freeze_value(value):
    """Recursively converts `value` into a deeply-immutable representation:
    a fresh `MappingProxyType` (never wrapping the caller's own dict) for
    mappings, a `tuple` for lists/tuples, and scalars unchanged (str/int/
    float/bool/None are already immutable). Because every container is
    rebuilt from scratch rather than wrapped in place, the ORIGINAL
    caller-owned dict/list can be freely mutated afterward with zero effect
    on the frozen result -- this is the alias-safety guarantee."""
    if isinstance(value, MappingProxyType):
        value = dict(value)
    if isinstance(value, dict):
        return MappingProxyType({k: freeze_value(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze_value(v) for v in value)
    return value


def _freeze_dataclass_metadata_fields(obj):
    """Returns `obj` with every dict-typed field ('metadata',
    'arguments_summary') replaced by its frozen form, via
    `dataclasses.replace` (obj itself is a frozen dataclass already)."""
    if not dataclasses.is_dataclass(obj) or isinstance(obj, type):
        return obj
    changes = {}
    for f in dataclasses.fields(obj):
        current = getattr(obj, f.name)
        if isinstance(current, (dict, MappingProxyType)):
            changes[f.name] = freeze_value(current)
    return dataclasses.replace(obj, **changes) if changes else obj


def deep_freeze(artifact: CognitiveArtifact) -> CognitiveArtifact:
    """Applied by `compiler.compile_artifact()` as the final step: makes
    every nested mutable container in the artifact (metadata dicts,
    ActionIntent.arguments_summary) deeply immutable, with no aliasing to
    any caller-owned object."""
    return dataclasses.replace(
        artifact,
        metadata=freeze_value(artifact.metadata),
        atoms=tuple(_freeze_dataclass_metadata_fields(a) for a in artifact.atoms),
        relations=tuple(_freeze_dataclass_metadata_fields(r) for r in artifact.relations),
        evidence=tuple(_freeze_dataclass_metadata_fields(e) for e in artifact.evidence),
        action_intents=tuple(_freeze_dataclass_metadata_fields(x) for x in artifact.action_intents),
    )


def _to_json_safe(value):
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _to_json_safe(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (tuple, list)):
        return [_to_json_safe(v) for v in value]
    if isinstance(value, (dict, MappingProxyType)):
        return {str(k): _to_json_safe(v) for k, v in value.items()}
    return value


def to_canonical_json(artifact: CognitiveArtifact) -> str:
    canonical = canonicalize(artifact)
    safe = _to_json_safe(canonical)
    try:
        return json.dumps(safe, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False)
    except ValueError as exc:
        raise InvalidCanonicalForm(f"artifact contains a non-canonicalizable value (e.g. NaN/Infinity): {exc}")


def digest(artifact: CognitiveArtifact) -> str:
    payload = to_canonical_json(artifact).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ── Strict wire parsing (section 6) ─────────────────────────────────────

_ARTIFACT_FIELDS = {f.name for f in dataclasses.fields(CognitiveArtifact)}


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    seen: dict = {}
    for key, value in pairs:
        if key in seen:
            raise DuplicateWireKey(f"duplicate JSON object key {key!r}")
        seen[key] = value
    return seen


def _reject_unknown_fields(d: dict, allowed: set[str], *, where: str) -> None:
    unknown = set(d.keys()) - allowed
    if unknown:
        raise UnknownWireField(f"{where}: unknown field(s) {sorted(unknown)!r} for schema 1.0.0")


def _required(d: dict, key: str, *, where: str):
    if key not in d:
        raise MissingMandatoryField(f"{where}: missing mandatory field {key!r}")
    return d[key]


def _safe_enum(enum_cls, raw, *, where: str):
    try:
        return enum_cls(raw)
    except ValueError:
        raise MalformedWireShape(f"{where}: {raw!r} is not a valid {enum_cls.__name__} value")


def parse_ocl_draft_json(text: str) -> CognitiveArtifact:
    """Parses UNTRUSTED wire input into an artifact object -- strictly
    (duplicate keys and unknown fields are rejected, missing mandatory
    fields and malformed enum values become typed `OclError` subclasses),
    but does NOT validate cross-references, authority, provenance rules,
    or graph shape. The result is a DRAFT, not a trusted artifact. Callers
    MUST pass it to `compiler.compile_artifact()` before treating it as
    valid -- this function's name deliberately does not say "safe" or
    "validated" on its own."""
    from orneur.intelligence.ocl import limits
    from orneur.intelligence.ocl.artifact import CognitiveArtifact as _Artifact
    from orneur.intelligence.ocl.causal import CausalHypothesis, CounterfactualBranch
    from orneur.intelligence.ocl.enums import AtomKind, EvidenceKind, ProducerKind, RelationKind, SourceClass
    from orneur.intelligence.ocl.errors import PayloadLimitExceeded
    from orneur.intelligence.ocl.evidence import EvidenceAnchor
    from orneur.intelligence.ocl.graph import CognitiveAtom, CognitiveRelation
    from orneur.intelligence.ocl.proposals import ActionIntent, EscalationRequest, VerificationContract
    from orneur.intelligence.ocl.provenance import ModelIdentityRef, Provenance

    raw_size = len(text.encode("utf-8"))
    if raw_size > limits.MAX_ARTIFACT_SERIALIZED_BYTES:
        raise PayloadLimitExceeded(
            f"wire payload is {raw_size} bytes, exceeding MAX_ARTIFACT_SERIALIZED_BYTES="
            f"{limits.MAX_ARTIFACT_SERIALIZED_BYTES} -- rejected before parsing"
        )

    try:
        data = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise MalformedWireShape(f"invalid JSON: {exc}")

    if not isinstance(data, dict):
        raise MalformedWireShape("top-level wire payload must be a JSON object")
    _reject_unknown_fields(data, _ARTIFACT_FIELDS, where="artifact")

    def identity_from(d) -> ModelIdentityRef | None:
        if d is None:
            return None
        allowed = {f.name for f in dataclasses.fields(ModelIdentityRef)}
        _reject_unknown_fields(d, allowed, where="provenance.model_identity")
        return ModelIdentityRef(**d)

    def provenance_from(d) -> Provenance:
        allowed = {f.name for f in dataclasses.fields(Provenance)}
        _reject_unknown_fields(d, allowed, where="provenance")
        return Provenance(
            producer_kind=_safe_enum(ProducerKind, _required(d, "producer_kind", where="provenance"), where="provenance.producer_kind"),
            producer_id=_required(d, "producer_id", where="provenance"),
            model_identity=identity_from(d.get("model_identity")),
            invocation_ref=d.get("invocation_ref"), schema_version=d.get("schema_version"),
        )

    def atom_from(d) -> CognitiveAtom:
        allowed = {f.name for f in dataclasses.fields(CognitiveAtom)}
        _reject_unknown_fields(d, allowed, where="atom")
        return CognitiveAtom(
            atom_id=_required(d, "atom_id", where="atom"),
            kind=_safe_enum(AtomKind, _required(d, "kind", where="atom"), where="atom.kind"),
            source_class=_safe_enum(SourceClass, _required(d, "source_class", where="atom"), where="atom.source_class"),
            content=_required(d, "content", where="atom"),
            namespace=d.get("namespace", "core"),
            evidence_refs=tuple(d.get("evidence_refs", ())), metadata=d.get("metadata", {}),
        )

    def relation_from(d) -> CognitiveRelation:
        allowed = {f.name for f in dataclasses.fields(CognitiveRelation)}
        _reject_unknown_fields(d, allowed, where="relation")
        return CognitiveRelation(
            relation_id=_required(d, "relation_id", where="relation"),
            kind=_safe_enum(RelationKind, _required(d, "kind", where="relation"), where="relation.kind"),
            source_atom_id=_required(d, "source_atom_id", where="relation"),
            target_atom_id=_required(d, "target_atom_id", where="relation"),
            namespace=d.get("namespace", "core"), metadata=d.get("metadata", {}),
        )

    def evidence_from(d) -> EvidenceAnchor:
        allowed = {f.name for f in dataclasses.fields(EvidenceAnchor)}
        _reject_unknown_fields(d, allowed, where="evidence")
        return EvidenceAnchor(
            evidence_id=_required(d, "evidence_id", where="evidence"),
            evidence_kind=_safe_enum(EvidenceKind, _required(d, "evidence_kind", where="evidence"), where="evidence.evidence_kind"),
            issuer=_required(d, "issuer", where="evidence"), reference=_required(d, "reference", where="evidence"),
            digest=d.get("digest"), observed_at=d.get("observed_at"), locator=d.get("locator"),
            metadata=d.get("metadata", {}),
        )

    def action_intent_from(d) -> ActionIntent:
        allowed = {f.name for f in dataclasses.fields(ActionIntent)}
        _reject_unknown_fields(d, allowed, where="action_intent")
        return ActionIntent(
            intent_id=_required(d, "intent_id", where="action_intent"),
            proposed_capability=_required(d, "proposed_capability", where="action_intent"),
            target_reference=d.get("target_reference"), arguments_summary=d.get("arguments_summary", {}),
            rationale_atom_refs=tuple(d.get("rationale_atom_refs", ())), expected_effect=d.get("expected_effect", ""),
            preconditions=tuple(d.get("preconditions", ())),
            verification_requirement_refs=tuple(d.get("verification_requirement_refs", ())),
            risk_hints=tuple(d.get("risk_hints", ())),
        )

    def verification_contract_from(d) -> VerificationContract:
        allowed = {f.name for f in dataclasses.fields(VerificationContract)}
        _reject_unknown_fields(d, allowed, where="verification_contract")
        return VerificationContract(
            contract_id=_required(d, "contract_id", where="verification_contract"),
            target_atom_ref=_required(d, "target_atom_ref", where="verification_contract"),
            required_evidence_kinds=tuple(d.get("required_evidence_kinds", ())),
            proposed_test=d.get("proposed_test", ""), pass_conditions=tuple(d.get("pass_conditions", ())),
            fail_conditions=tuple(d.get("fail_conditions", ())),
            verification_scope_ref=d.get("verification_scope_ref"), status=d.get("status", "UNRESOLVED"),
        )

    def escalation_request_from(d) -> EscalationRequest:
        allowed = {f.name for f in dataclasses.fields(EscalationRequest)}
        _reject_unknown_fields(d, allowed, where="escalation_request")
        return EscalationRequest(
            escalation_id=_required(d, "escalation_id", where="escalation_request"),
            triggering_atom_refs=tuple(d.get("triggering_atom_refs", ())),
            reason_categories=tuple(d.get("reason_categories", ())),
            unresolved_conflict_refs=tuple(d.get("unresolved_conflict_refs", ())),
            requested_capability_type=d.get("requested_capability_type", ""),
            evidence_deficit=d.get("evidence_deficit", ""),
            requested_cognitive_role=d.get("requested_cognitive_role"),
        )

    def causal_hypothesis_from(d) -> CausalHypothesis:
        allowed = {f.name for f in dataclasses.fields(CausalHypothesis)}
        _reject_unknown_fields(d, allowed, where="causal_hypothesis")
        return CausalHypothesis(
            hypothesis_id=_required(d, "hypothesis_id", where="causal_hypothesis"),
            cause_atom_ref=_required(d, "cause_atom_ref", where="causal_hypothesis"),
            mechanism=_required(d, "mechanism", where="causal_hypothesis"),
            predicted_consequence_atom_ref=_required(d, "predicted_consequence_atom_ref", where="causal_hypothesis"),
            observable_test_ref=d.get("observable_test_ref"),
            observed_evidence_refs=tuple(d.get("observed_evidence_refs", ())),
        )

    def counterfactual_branch_from(d) -> CounterfactualBranch:
        allowed = {f.name for f in dataclasses.fields(CounterfactualBranch)}
        _reject_unknown_fields(d, allowed, where="counterfactual_branch")
        return CounterfactualBranch(
            branch_id=_required(d, "branch_id", where="counterfactual_branch"),
            causal_hypothesis_ref=_required(d, "causal_hypothesis_ref", where="counterfactual_branch"),
            condition_atom_ref=_required(d, "condition_atom_ref", where="counterfactual_branch"),
            predicted_atom_ref=_required(d, "predicted_atom_ref", where="counterfactual_branch"),
        )

    return _Artifact(
        artifact_id=_required(data, "artifact_id", where="artifact"),
        schema_version=_required(data, "schema_version", where="artifact"),
        request_id=_required(data, "request_id", where="artifact"),
        provenance=provenance_from(_required(data, "provenance", where="artifact")),
        created_at=_required(data, "created_at", where="artifact"),
        atoms=tuple(atom_from(a) for a in data.get("atoms", ())),
        relations=tuple(relation_from(r) for r in data.get("relations", ())),
        evidence=tuple(evidence_from(e) for e in data.get("evidence", ())),
        action_intents=tuple(action_intent_from(x) for x in data.get("action_intents", ())),
        verification_contracts=tuple(verification_contract_from(x) for x in data.get("verification_contracts", ())),
        escalation_requests=tuple(escalation_request_from(x) for x in data.get("escalation_requests", ())),
        causal_hypotheses=tuple(causal_hypothesis_from(x) for x in data.get("causal_hypotheses", ())),
        counterfactual_branches=tuple(counterfactual_branch_from(x) for x in data.get("counterfactual_branches", ())),
        limitation_atom_refs=tuple(data.get("limitation_atom_refs", ())),
        metadata=data.get("metadata", {}),
        parent_artifact_id=data.get("parent_artifact_id"),
        transformation_id=data.get("transformation_id"),
    )


def compile_ocl_json(text: str) -> CognitiveArtifact:
    """The safe, validated public entry point for untrusted wire input:
    parse (strictly) THEN compile (fully validate). Prefer this over
    calling `parse_ocl_draft_json()` directly unless you specifically need
    the unvalidated draft for inspection."""
    from orneur.intelligence.ocl.compiler import compile_artifact
    return compile_artifact(parse_ocl_draft_json(text))
