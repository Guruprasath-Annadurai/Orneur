"""
Phase 18 deterministic resolver: the single place canonical
EpistemicState is computed. See
docs/orneur/phase-18/PHASE18_EPISTEMIC_STATE_SPEC.md for the full
normative algorithm and precedence rationale.

Hard invariant: nothing here ever reads CognitiveArtifact/atom/evidence
`metadata` to decide state. All evidence resolutions and feasibility
records arrive as explicit, separately-typed parameters
(resolved_evidence / feasibility_records), gated by a single explicit
resolution_trust_context enum member supplied by the caller -- never by
a model, never parsed from a wire payload, never inferred from a field
that merely happens to be named "verified" or "confidence" inside
untrusted data. This is what makes self-elevation structurally
impossible rather than merely discouraged.
"""
from __future__ import annotations

import uuid
from collections import defaultdict

from orneur.intelligence.epistemic import errors, trust
from orneur.intelligence.epistemic.enums import (
    CURRENT_SCHEMA_VERSION,
    EPISTEMICALLY_ASSESSABLE_ATOM_KINDS,
    EpistemicPolarity,
    EpistemicReasonCode,
    EpistemicResolutionTrustContext,
    EpistemicState,
    EvidenceResolutionStatus,
    EvidenceStance,
    RelationEffect,
    VerificationFeasibility,
    get_relation_semantics,
)
from orneur.intelligence.epistemic.graph import compute_evidence_rooted_reachability
from orneur.intelligence.epistemic.limits import (
    MAX_ATOMS_ASSESSED,
    MAX_EVIDENCE_RESOLUTIONS,
    MAX_FEASIBILITY_RECORDS,
)
from orneur.intelligence.epistemic.models import EpistemicAssessment, EpistemicOverlay, ResolvedEvidence, VerificationFeasibilityRecord
from orneur.intelligence.epistemic.typecheck import require_instance, require_sequence_container, require_string
from orneur.intelligence.ocl.artifact import CognitiveArtifact
from orneur.intelligence.ocl.compiler import compile_artifact
from orneur.intelligence.ocl.enums import RelationKind
from orneur.intelligence.ocl.trust import CompilationTrustContext
from orneur.intelligence.ocl import canonical as ocl_canonical


def assess_artifact(
    draft_or_artifact: CognitiveArtifact,
    *,
    ocl_trust_context: CompilationTrustContext,
    resolved_evidence: tuple[ResolvedEvidence, ...] | list[ResolvedEvidence] = (),
    feasibility_records: tuple[VerificationFeasibilityRecord, ...] | list[VerificationFeasibilityRecord] = (),
    resolution_trust_context: EpistemicResolutionTrustContext = trust.UNTRUSTED,
    assessment_context_id: str,
    assessed_at: str,
    target_atom_ids: tuple[str, ...] | None = None,
    overlay_id: str | None = None,
    metadata: dict | None = None,
) -> EpistemicOverlay:
    """Deterministically assess one OCL artifact. Same artifact + same
    evidence/feasibility snapshot + same assessment_context_id +
    same assessed_at => byte-identical canonical overlay (see
    canonical.digest). Re-validates/recompiles `draft_or_artifact`
    through OCL's own compile_artifact() at the boundary -- never trusts
    an object merely because its type is CognitiveArtifact."""
    require_instance(ocl_trust_context, CompilationTrustContext, where="ocl_trust_context")
    artifact = compile_artifact(draft_or_artifact, trust_context=ocl_trust_context)

    if not trust.is_valid_resolution_trust_context(resolution_trust_context):
        raise errors.InvalidResolutionTrustContext(
            f"resolution_trust_context must be a genuine EpistemicResolutionTrustContext member, "
            f"got {type(resolution_trust_context).__name__}"
        )

    resolved_evidence = require_sequence_container(resolved_evidence, where="resolved_evidence")
    feasibility_records = require_sequence_container(feasibility_records, where="feasibility_records")
    if len(resolved_evidence) > MAX_EVIDENCE_RESOLUTIONS:
        raise errors.PayloadLimitExceeded("resolved_evidence exceeds MAX_EVIDENCE_RESOLUTIONS")
    if len(feasibility_records) > MAX_FEASIBILITY_RECORDS:
        raise errors.PayloadLimitExceeded("feasibility_records exceeds MAX_FEASIBILITY_RECORDS")
    for entry in resolved_evidence:
        require_instance(entry, ResolvedEvidence, where="resolved_evidence[]")
    for entry in feasibility_records:
        require_instance(entry, VerificationFeasibilityRecord, where="feasibility_records[]")

    require_string(assessment_context_id, where="assessment_context_id")
    require_string(assessed_at, where="assessed_at")
    _validate_iso8601(assessed_at)

    atoms_by_id = {atom.atom_id: atom for atom in artifact.atoms}
    evidence_ids = {e.evidence_id for e in artifact.evidence}

    if target_atom_ids is None:
        assess_ids = tuple(
            atom.atom_id for atom in artifact.atoms if atom.kind in EPISTEMICALLY_ASSESSABLE_ATOM_KINDS
        )
    else:
        target_atom_ids = require_sequence_container(target_atom_ids, where="target_atom_ids")
        for atom_id in target_atom_ids:
            require_string(atom_id, where="target_atom_ids[]")
            if atom_id not in atoms_by_id:
                raise errors.UnknownAtomReference(f"target atom not present in artifact: {atom_id!r}")
            if atoms_by_id[atom_id].kind not in EPISTEMICALLY_ASSESSABLE_ATOM_KINDS:
                raise errors.NonAssessableAtomKind(
                    f"atom {atom_id!r} has kind {atoms_by_id[atom_id].kind.value}, "
                    f"which is not in EPISTEMICALLY_ASSESSABLE_ATOM_KINDS"
                )
        assess_ids = tuple(target_atom_ids)

    if len(assess_ids) > MAX_ATOMS_ASSESSED:
        raise errors.GraphLimitExceeded("assessed atom count exceeds MAX_ATOMS_ASSESSED")

    _validate_resolution_targets(resolved_evidence, atoms_by_id, evidence_ids)
    _validate_feasibility_targets(feasibility_records, atoms_by_id)
    _reject_conflicting_resolutions(resolved_evidence)

    qualified = trust.is_qualified(resolution_trust_context)
    can_mint_unverifiable = trust.can_mint_structurally_unverifiable(resolution_trust_context)

    direct_support_evidence_by_atom: dict[str, tuple[str, ...]] = defaultdict(tuple)
    direct_refutation_evidence_by_atom: dict[str, tuple[str, ...]] = defaultdict(tuple)
    unresolved_evidence_by_atom: dict[str, tuple[str, ...]] = defaultdict(tuple)
    reason_signals_by_atom: dict[str, set[EpistemicReasonCode]] = defaultdict(set)

    for record in resolved_evidence:
        if qualified and record.status is EvidenceResolutionStatus.VERIFIED and record.stance is EvidenceStance.SUPPORTS:
            direct_support_evidence_by_atom[record.target_atom_id] += (record.evidence_id,)
        elif qualified and record.status is EvidenceResolutionStatus.VERIFIED and record.stance is EvidenceStance.REFUTES:
            direct_refutation_evidence_by_atom[record.target_atom_id] += (record.evidence_id,)
        else:
            unresolved_evidence_by_atom[record.target_atom_id] += (record.evidence_id,)
            reason_signals_by_atom[record.target_atom_id].add(_unresolved_reason(record, qualified))

    feasibility_by_atom: dict[str, VerificationFeasibilityRecord] = {}
    for record in feasibility_records:
        feasibility_by_atom[record.target_atom_id] = record
        if record.feasibility is VerificationFeasibility.PENDING:
            reason_signals_by_atom[record.target_atom_id].add(EpistemicReasonCode.VERIFICATION_PENDING)
        elif record.feasibility is VerificationFeasibility.TEMPORARILY_UNAVAILABLE:
            reason_signals_by_atom[record.target_atom_id].add(EpistemicReasonCode.TEMPORARY_VERIFICATION_UNAVAILABLE)

    direct_support_roots = frozenset(direct_support_evidence_by_atom)
    direct_refutation_roots = frozenset(direct_refutation_evidence_by_atom)
    support_reachable, refutation_reachable = compute_evidence_rooted_reachability(
        artifact.relations, direct_support_roots, direct_refutation_roots,
    )

    contradicts_pairs = _collect_contradicts(artifact.relations)
    unqualified_contradiction_atoms = _unqualified_contradiction_atoms(
        contradicts_pairs, support_reachable, refutation_reachable,
    )

    assessments = []
    for atom_id in assess_ids:
        assessments.append(
            _assess_one_atom(
                atom_id=atom_id,
                direct_support_evidence=direct_support_evidence_by_atom.get(atom_id, ()),
                direct_refutation_evidence=direct_refutation_evidence_by_atom.get(atom_id, ()),
                unresolved_evidence=unresolved_evidence_by_atom.get(atom_id, ()),
                extra_reason_signals=reason_signals_by_atom.get(atom_id, set()),
                support_reachable=support_reachable,
                refutation_reachable=refutation_reachable,
                is_unqualified_contradiction=atom_id in unqualified_contradiction_atoms,
                contradiction_atom_refs=contradicts_pairs.get(atom_id, ()),
                feasibility_record=feasibility_by_atom.get(atom_id),
                can_mint_unverifiable=can_mint_unverifiable,
            )
        )

    source_digest = ocl_canonical.digest(artifact)
    context_digest = _assessment_context_digest(
        assessment_context_id=assessment_context_id,
        resolved_evidence=resolved_evidence,
        feasibility_records=feasibility_records,
        resolution_trust_context=resolution_trust_context,
    )

    overlay = EpistemicOverlay(
        overlay_id=overlay_id or str(uuid.uuid4()),
        schema_version=CURRENT_SCHEMA_VERSION,
        source_artifact_id=artifact.artifact_id,
        source_artifact_digest=source_digest,
        assessment_context_digest=context_digest,
        assessed_at=assessed_at,
        assessments=tuple(sorted(assessments, key=lambda a: a.atom_id)),
        metadata=_freeze_metadata(metadata or {}),
    )
    return overlay


def verify_overlay_binding(overlay: EpistemicOverlay, artifact: CognitiveArtifact) -> None:
    """Raise SourceArtifactMismatch unless `overlay` was assessed
    against exactly this canonical artifact (same id AND same content
    digest). Must be called before any consumer treats an overlay as
    still valid for a given artifact -- an overlay is never silently
    reused across a mutation/recompilation."""
    if overlay.source_artifact_id != artifact.artifact_id:
        raise errors.SourceArtifactMismatch(
            f"overlay source_artifact_id {overlay.source_artifact_id!r} != "
            f"artifact.artifact_id {artifact.artifact_id!r}"
        )
    actual_digest = ocl_canonical.digest(artifact)
    if overlay.source_artifact_digest != actual_digest:
        raise errors.SourceArtifactMismatch(
            "overlay source_artifact_digest does not match the artifact's current canonical digest "
            "-- the artifact was mutated/recompiled since this overlay was produced"
        )


# ── internal helpers ────────────────────────────────────────────────────


def _validate_iso8601(value: str) -> None:
    import datetime

    try:
        datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise errors.InvalidAssessmentContext(f"assessed_at is not a valid ISO-8601 timestamp: {exc}") from exc


def _validate_resolution_targets(resolved_evidence, atoms_by_id: dict, evidence_ids: set) -> None:
    for record in resolved_evidence:
        require_string(record.evidence_id, where="ResolvedEvidence.evidence_id")
        require_string(record.target_atom_id, where="ResolvedEvidence.target_atom_id")
        if record.evidence_id not in evidence_ids:
            raise errors.UnknownEvidenceReference(f"unknown evidence_id: {record.evidence_id!r}")
        atom = atoms_by_id.get(record.target_atom_id)
        if atom is None:
            raise errors.UnknownAtomReference(f"unknown target_atom_id: {record.target_atom_id!r}")
        if record.evidence_id not in atom.evidence_refs:
            raise errors.EvidenceAtomMismatch(
                f"evidence {record.evidence_id!r} is not among atom {record.target_atom_id!r}'s evidence_refs"
            )


def _validate_feasibility_targets(feasibility_records, atoms_by_id: dict) -> None:
    for record in feasibility_records:
        require_string(record.target_atom_id, where="VerificationFeasibilityRecord.target_atom_id")
        if record.target_atom_id not in atoms_by_id:
            raise errors.UnknownAtomReference(f"unknown target_atom_id: {record.target_atom_id!r}")


def _reject_conflicting_resolutions(resolved_evidence) -> None:
    seen: dict[tuple[str, str], ResolvedEvidence] = {}
    for record in resolved_evidence:
        key = (record.target_atom_id, record.evidence_id)
        prior = seen.get(key)
        if prior is not None and (prior.status, prior.stance) != (record.status, record.stance):
            raise errors.ConflictingEvidenceResolution(
                f"conflicting resolutions for atom={record.target_atom_id!r} evidence={record.evidence_id!r}: "
                f"({prior.status.value}, {prior.stance.value}) vs ({record.status.value}, {record.stance.value})"
            )
        if prior is not None:
            # exact duplicate submission -- fail closed rather than
            # silently deduping, per "do not silently pick one".
            raise errors.ConflictingEvidenceResolution(
                f"duplicate resolution record for atom={record.target_atom_id!r} evidence={record.evidence_id!r}"
            )
        seen[key] = record


def _unresolved_reason(record: ResolvedEvidence, qualified: bool) -> EpistemicReasonCode:
    if not qualified:
        return EpistemicReasonCode.UNVERIFIED_EVIDENCE
    if record.status is EvidenceResolutionStatus.UNVERIFIED:
        return EpistemicReasonCode.UNVERIFIED_EVIDENCE
    if record.status is EvidenceResolutionStatus.STALE:
        return EpistemicReasonCode.STALE_EVIDENCE
    if record.status is EvidenceResolutionStatus.UNAVAILABLE:
        return EpistemicReasonCode.EVIDENCE_UNAVAILABLE
    if record.status is EvidenceResolutionStatus.INVALID:
        return EpistemicReasonCode.EVIDENCE_INVALID
    # VERIFIED + INCONCLUSIVE
    return EpistemicReasonCode.EVIDENCE_INCONCLUSIVE


def _collect_contradicts(relations) -> dict[str, tuple[str, ...]]:
    pairs: dict[str, tuple[str, ...]] = defaultdict(tuple)
    for relation in relations:
        if get_relation_semantics(relation.kind).effect is RelationEffect.CONFLICT:
            pairs[relation.source_atom_id] += (relation.target_atom_id,)
            pairs[relation.target_atom_id] += (relation.source_atom_id,)
    return pairs


def _unqualified_contradiction_atoms(contradicts_pairs, support_reachable, refutation_reachable) -> set[str]:
    flagged: set[str] = set()
    for atom_id, others in contradicts_pairs.items():
        atom_established = atom_id in support_reachable or atom_id in refutation_reachable
        for other_id in others:
            other_established = other_id in support_reachable or other_id in refutation_reachable
            if not atom_established and not other_established:
                flagged.add(atom_id)
                flagged.add(other_id)
    return flagged


def _assess_one_atom(
    *,
    atom_id: str,
    direct_support_evidence: tuple[str, ...],
    direct_refutation_evidence: tuple[str, ...],
    unresolved_evidence: tuple[str, ...],
    extra_reason_signals: set[EpistemicReasonCode],
    support_reachable: dict,
    refutation_reachable: dict,
    is_unqualified_contradiction: bool,
    contradiction_atom_refs: tuple[str, ...],
    feasibility_record: VerificationFeasibilityRecord | None,
    can_mint_unverifiable: bool,
) -> EpistemicAssessment:
    has_direct_support = bool(direct_support_evidence)
    has_direct_refutation = bool(direct_refutation_evidence)
    derived_support_refs = tuple(sorted(support_reachable.get(atom_id, ()))) if atom_id in support_reachable and not has_direct_support else ()
    derived_refutation_refs = tuple(sorted(refutation_reachable.get(atom_id, ()))) if atom_id in refutation_reachable and not has_direct_refutation else ()
    has_derived_support = atom_id in support_reachable and not has_direct_support
    has_derived_refutation = atom_id in refutation_reachable and not has_direct_refutation

    any_support = has_direct_support or has_derived_support
    any_refutation = has_direct_refutation or has_derived_refutation

    reason_codes: set[EpistemicReasonCode] = set()

    if any_support and any_refutation:
        state = EpistemicState.DISPUTED
        polarity = EpistemicPolarity.MIXED
        reason_codes.add(EpistemicReasonCode.VERIFIED_CONTRADICTION)
    elif has_direct_support:
        state = EpistemicState.KNOWN
        polarity = EpistemicPolarity.AFFIRMED
        reason_codes.add(EpistemicReasonCode.DIRECT_VERIFIED_SUPPORT)
    elif has_direct_refutation:
        state = EpistemicState.KNOWN
        polarity = EpistemicPolarity.REFUTED
        reason_codes.add(EpistemicReasonCode.DIRECT_VERIFIED_REFUTATION)
    elif has_derived_support:
        state = EpistemicState.INFERRED
        polarity = EpistemicPolarity.AFFIRMED
        reason_codes.add(EpistemicReasonCode.EVIDENCE_BACKED_DERIVATION)
    elif has_derived_refutation:
        state = EpistemicState.INFERRED
        polarity = EpistemicPolarity.REFUTED
        reason_codes.add(EpistemicReasonCode.EVIDENCE_BACKED_DERIVATION)
    elif (
        can_mint_unverifiable
        and feasibility_record is not None
        and feasibility_record.feasibility is VerificationFeasibility.STRUCTURALLY_UNVERIFIABLE
    ):
        state = EpistemicState.UNVERIFIABLE
        polarity = EpistemicPolarity.UNRESOLVED
        reason_codes.add(EpistemicReasonCode.STRUCTURALLY_UNVERIFIABLE)
    else:
        if is_unqualified_contradiction:
            reason_codes.add(EpistemicReasonCode.UNQUALIFIED_CONTRADICTION)
        reason_codes |= extra_reason_signals
        if reason_codes:
            state = EpistemicState.UNCERTAIN
            polarity = EpistemicPolarity.UNRESOLVED
        else:
            state = EpistemicState.UNKNOWN
            polarity = EpistemicPolarity.UNRESOLVED
            reason_codes.add(EpistemicReasonCode.NO_EPISTEMIC_BASIS)

    return EpistemicAssessment(
        atom_id=atom_id,
        state=state,
        polarity=polarity,
        direct_support_evidence_refs=tuple(sorted(direct_support_evidence)),
        direct_refutation_evidence_refs=tuple(sorted(direct_refutation_evidence)),
        derived_support_atom_refs=derived_support_refs,
        derived_refutation_atom_refs=derived_refutation_refs,
        unresolved_evidence_refs=tuple(sorted(unresolved_evidence)),
        contradiction_atom_refs=tuple(sorted(contradiction_atom_refs)),
        verification_contract_refs=(),
        reason_codes=tuple(sorted(reason_codes, key=lambda r: r.value)),
    )


def _assessment_context_digest(
    *,
    assessment_context_id: str,
    resolved_evidence,
    feasibility_records,
    resolution_trust_context: EpistemicResolutionTrustContext,
) -> str:
    import hashlib
    import json

    payload = {
        "assessment_context_id": assessment_context_id,
        "resolution_trust_context": resolution_trust_context.value,
        "resolved_evidence": sorted(
            (
                {
                    "evidence_id": r.evidence_id,
                    "target_atom_id": r.target_atom_id,
                    "status": r.status.value,
                    "stance": r.stance.value,
                    "resolver_reference": r.resolver_reference,
                    "resolved_at": r.resolved_at,
                }
                for r in resolved_evidence
            ),
            key=lambda d: (d["target_atom_id"], d["evidence_id"]),
        ),
        "feasibility_records": sorted(
            (
                {
                    "target_atom_id": f.target_atom_id,
                    "feasibility": f.feasibility.value,
                    "verifier_reference": f.verifier_reference,
                    "recorded_at": f.recorded_at,
                }
                for f in feasibility_records
            ),
            key=lambda d: d["target_atom_id"],
        ),
    }
    canonical_bytes = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest()


def _freeze_metadata(metadata: dict):
    from types import MappingProxyType

    require_instance(metadata, dict, where="metadata")
    return MappingProxyType(dict(metadata))
