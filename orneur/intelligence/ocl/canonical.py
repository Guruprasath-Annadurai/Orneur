"""
Canonicalization + content digest (spec sections 15, 23, 25).

`canonicalize(artifact)` returns a NEW `CognitiveArtifact` whose
collections are sorted into a stable, deterministic order -- it never
mutates the input (frozen dataclasses can't be mutated anyway) and never
generates new random IDs. `digest(artifact)` returns a SHA-256 hex digest
of the canonical JSON form -- stdlib crypto only, no custom scheme, and no
claim of cryptographic authentication (a digest proves content identity,
not who produced it or that it wasn't tampered with in transit; that is a
separate, unimplemented signing concern).
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from enum import Enum

from orneur.intelligence.ocl.artifact import CognitiveArtifact
from orneur.intelligence.ocl.errors import InvalidCanonicalForm


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


def _to_json_safe(value):
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _to_json_safe(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (tuple, list)):
        return [_to_json_safe(v) for v in value]
    if isinstance(value, dict):
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


def artifact_from_dict(data: dict) -> CognitiveArtifact:
    """Reconstructs a `CognitiveArtifact` from its JSON-safe dict form
    (the inverse of `_to_json_safe` applied to an artifact). Safe parsing
    only -- plain `dict`/`list`/`str` traversal, no `eval`/`pickle`/
    arbitrary code execution of any kind."""
    from orneur.intelligence.ocl.artifact import CognitiveArtifact
    from orneur.intelligence.ocl.causal import CausalHypothesis, CounterfactualBranch
    from orneur.intelligence.ocl.enums import AtomKind, ProducerKind, RelationKind, SourceClass
    from orneur.intelligence.ocl.evidence import EvidenceAnchor
    from orneur.intelligence.ocl.graph import CognitiveAtom, CognitiveRelation
    from orneur.intelligence.ocl.proposals import ActionIntent, EscalationRequest, VerificationContract
    from orneur.intelligence.ocl.provenance import ModelIdentityRef, Provenance

    def atom_from(d: dict) -> CognitiveAtom:
        return CognitiveAtom(
            atom_id=d["atom_id"], kind=AtomKind(d["kind"]), source_class=SourceClass(d["source_class"]),
            content=d["content"], namespace=d.get("namespace", "core"),
            evidence_refs=tuple(d.get("evidence_refs", ())), metadata=d.get("metadata", {}),
        )

    def relation_from(d: dict) -> CognitiveRelation:
        return CognitiveRelation(
            relation_id=d["relation_id"], kind=RelationKind(d["kind"]),
            source_atom_id=d["source_atom_id"], target_atom_id=d["target_atom_id"],
            namespace=d.get("namespace", "core"), metadata=d.get("metadata", {}),
        )

    def evidence_from(d: dict) -> EvidenceAnchor:
        from orneur.intelligence.ocl.enums import EvidenceKind
        return EvidenceAnchor(
            evidence_id=d["evidence_id"], evidence_kind=EvidenceKind(d["evidence_kind"]),
            issuer=d["issuer"], reference=d["reference"], digest=d.get("digest"),
            observed_at=d.get("observed_at"), locator=d.get("locator"), metadata=d.get("metadata", {}),
        )

    def identity_from(d: dict | None) -> ModelIdentityRef | None:
        return None if d is None else ModelIdentityRef(**d)

    def provenance_from(d: dict) -> Provenance:
        return Provenance(
            producer_kind=ProducerKind(d["producer_kind"]), producer_id=d["producer_id"],
            model_identity=identity_from(d.get("model_identity")),
            invocation_ref=d.get("invocation_ref"), schema_version=d.get("schema_version"),
        )

    return CognitiveArtifact(
        artifact_id=data["artifact_id"], schema_version=data["schema_version"], request_id=data["request_id"],
        provenance=provenance_from(data["provenance"]), created_at=data["created_at"],
        atoms=tuple(atom_from(a) for a in data.get("atoms", ())),
        relations=tuple(relation_from(r) for r in data.get("relations", ())),
        evidence=tuple(evidence_from(e) for e in data.get("evidence", ())),
        action_intents=tuple(
            ActionIntent(
                intent_id=x["intent_id"], proposed_capability=x["proposed_capability"],
                target_reference=x.get("target_reference"), arguments_summary=x.get("arguments_summary", {}),
                rationale_atom_refs=tuple(x.get("rationale_atom_refs", ())), expected_effect=x.get("expected_effect", ""),
                preconditions=tuple(x.get("preconditions", ())),
                verification_requirement_refs=tuple(x.get("verification_requirement_refs", ())),
                risk_hints=tuple(x.get("risk_hints", ())),
            )
            for x in data.get("action_intents", ())
        ),
        verification_contracts=tuple(
            VerificationContract(
                contract_id=x["contract_id"], target_atom_ref=x["target_atom_ref"],
                required_evidence_kinds=tuple(x.get("required_evidence_kinds", ())),
                proposed_test=x.get("proposed_test", ""), pass_conditions=tuple(x.get("pass_conditions", ())),
                fail_conditions=tuple(x.get("fail_conditions", ())),
                verification_scope_ref=x.get("verification_scope_ref"), status=x.get("status", "UNRESOLVED"),
            )
            for x in data.get("verification_contracts", ())
        ),
        escalation_requests=tuple(
            EscalationRequest(
                escalation_id=x["escalation_id"], triggering_atom_refs=tuple(x.get("triggering_atom_refs", ())),
                reason_categories=tuple(x.get("reason_categories", ())),
                unresolved_conflict_refs=tuple(x.get("unresolved_conflict_refs", ())),
                requested_capability_type=x.get("requested_capability_type", ""),
                evidence_deficit=x.get("evidence_deficit", ""),
                requested_cognitive_role=x.get("requested_cognitive_role"),
            )
            for x in data.get("escalation_requests", ())
        ),
        causal_hypotheses=tuple(
            CausalHypothesis(
                hypothesis_id=x["hypothesis_id"], cause_atom_ref=x["cause_atom_ref"], mechanism=x["mechanism"],
                predicted_consequence_atom_ref=x["predicted_consequence_atom_ref"],
                observable_test_ref=x.get("observable_test_ref"),
                observed_evidence_refs=tuple(x.get("observed_evidence_refs", ())),
            )
            for x in data.get("causal_hypotheses", ())
        ),
        counterfactual_branches=tuple(
            CounterfactualBranch(
                branch_id=x["branch_id"], causal_hypothesis_ref=x["causal_hypothesis_ref"],
                condition_atom_ref=x["condition_atom_ref"], predicted_atom_ref=x["predicted_atom_ref"],
            )
            for x in data.get("counterfactual_branches", ())
        ),
        limitation_atom_refs=tuple(data.get("limitation_atom_refs", ())),
        metadata=data.get("metadata", {}),
        parent_artifact_id=data.get("parent_artifact_id"),
        transformation_id=data.get("transformation_id"),
    )


def artifact_from_canonical_json(text: str) -> CognitiveArtifact:
    """Parses untrusted wire input. The raw byte length is checked BEFORE
    `json.loads` runs (threat model #32: parser resource exhaustion) --
    rejecting an oversized payload after parsing would have already paid
    the parsing cost."""
    from orneur.intelligence.ocl import limits
    from orneur.intelligence.ocl.errors import PayloadLimitExceeded

    raw_size = len(text.encode("utf-8"))
    if raw_size > limits.MAX_ARTIFACT_SERIALIZED_BYTES:
        raise PayloadLimitExceeded(
            f"wire payload is {raw_size} bytes, exceeding MAX_ARTIFACT_SERIALIZED_BYTES="
            f"{limits.MAX_ARTIFACT_SERIALIZED_BYTES} -- rejected before parsing"
        )
    return artifact_from_dict(json.loads(text))
