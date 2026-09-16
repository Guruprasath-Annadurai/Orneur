"""
Phase 20 deterministic evaluator: the single place a RoutingDecision is
computed. See docs/PHASE20_INTELLIGENCE_ROUTER.md for the full
normative algorithm.

Hard invariant: this module never calls a model, a tool, or any network
endpoint. It is pure deterministic code over already-trusted Phase 18/19
data (a verified-bound-and-provenance-checked EpistemicOverlay, an
optional Phase-19 IntegrityReceipt) and untrusted Phase 20 input (a
CognitiveTaskProfile) -- exactly mirroring the OCL-compiler /
Phase-18-resolver / Phase-19-evaluator boundary discipline one layer up.

Routing is not authority: a RoutingDecision is DATA. It never grants
execution/policy/Court/approval/promotion/security authority. See
docs/PHASE20_INTELLIGENCE_ROUTER.md's "Non-authority doctrine" and
tests/router/test_no_authority.py.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json

from orneur.intelligence.epistemic import EpistemicOverlay, EpistemicState
from orneur.intelligence.integrity import IntegrityReceipt, IntegrityStatus
from orneur.intelligence.integrity import overlay_trust
from orneur.intelligence.integrity.enums import IntegrityOverlayTrustContext
from orneur.intelligence.ocl import canonical as ocl_canonical
from orneur.intelligence.ocl.artifact import CognitiveArtifact
from orneur.intelligence.router import errors, registry as registry_module
from orneur.intelligence.router.contracts import (
    CognitiveTaskProfile,
    IntelligenceCapabilityProfile,
    MaterialEpistemicFactor,
    RoutingCandidateEvaluation,
    RoutingDecision,
)
from orneur.intelligence.router.enums import (
    CURRENT_PROTOCOL_VERSION,
    IMPLEMENTATION_REQUIREMENT_KINDS,
    INVESTIGATIVE_REQUIREMENT_KINDS,
    CognitiveFamily,
    CognitiveRequirementKind,
    RoutingReasonCode,
    RoutingStatus,
)
from orneur.intelligence.router.freeze import require_mapping_root, validate_and_freeze
from orneur.intelligence.router.limits import MAX_MATERIAL_ATOMS_PER_TASK, MAX_REQUIREMENTS_PER_TASK
from orneur.intelligence.router.typecheck import require_enum_member, require_instance, require_string

_REVIEW_TRIGGER_KINDS = frozenset({
    CognitiveRequirementKind.ADVERSARIAL_REVIEW,
    CognitiveRequirementKind.SECURITY_SENSITIVE_REASONING,
    CognitiveRequirementKind.HIGH_CONSEQUENCE_REASONING,
})


def route_task(
    task: CognitiveTaskProfile,
    *,
    overlay: EpistemicOverlay,
    artifact: CognitiveArtifact,
    overlay_trust_context: IntegrityOverlayTrustContext = overlay_trust.UNTRUSTED,
    expected_overlay_digest: str | None = None,
    integrity_receipt: IntegrityReceipt | None = None,
    capability_registry: tuple[IntelligenceCapabilityProfile, ...] | None = None,
    decision_id: str | None = None,
    metadata: dict | None = None,
) -> RoutingDecision:
    """Deterministically route `task` given a trusted `overlay`
    (verified via the REUSED Phase-19 `overlay_trust.verify_trusted_overlay`
    seam -- this function never derives `expected_overlay_digest` from
    `overlay` itself). Same task + same overlay + same integrity_receipt
    + same registry => byte-identical canonical decision (see
    canonical.digest)."""
    require_instance(task, CognitiveTaskProfile, where="task")
    require_instance(overlay, EpistemicOverlay, where="overlay")
    require_instance(artifact, CognitiveArtifact, where="artifact")
    if integrity_receipt is not None:
        require_instance(integrity_receipt, IntegrityReceipt, where="integrity_receipt")
    if decision_id is not None:
        require_string(decision_id, where="decision_id")

    # REUSED, not duplicated: the exact same overlay-trust-boundary seam
    # Phase 19 uses internally. Never compute expected_overlay_digest
    # from `overlay` here -- that would prove nothing and would
    # reintroduce the forged-overlay defect Phase 19 just closed.
    overlay_digest = overlay_trust.verify_trusted_overlay(
        overlay, artifact, trust_context=overlay_trust_context, expected_overlay_digest=expected_overlay_digest,
    )

    task = _validate_and_normalize_task(task)
    validated_registry = (
        registry_module.build_default_capability_registry()
        if capability_registry is None
        else registry_module.validate_registry(capability_registry)
    )

    assessments_by_atom = {a.atom_id: a for a in overlay.assessments}
    for atom_id in task.material_epistemic_atom_ids:
        if atom_id not in assessments_by_atom:
            raise errors.UnknownEpistemicAtomReference(
                f"task.material_epistemic_atom_ids contains {atom_id!r}, which the supplied overlay never assessed"
            )
    material_factors = tuple(
        MaterialEpistemicFactor(atom_id=atom_id, epistemic_state=assessments_by_atom[atom_id].state)
        for atom_id in sorted(task.material_epistemic_atom_ids)
    )

    source_digest = ocl_canonical.digest(artifact)
    registry_dig = registry_module.registry_digest(validated_registry)
    task_dig = _task_digest(task)

    metadata_root = require_mapping_root(metadata if metadata is not None else {}, where="metadata")
    frozen_metadata = validate_and_freeze(metadata_root, where="metadata")

    # Integrity failure blocks routing outright -- an integrity-blocked
    # input is never routed as if it were clean, and Cognitive
    # Conservation still applies: material epistemic factors remain
    # represented even on the blocked path.
    if integrity_receipt is not None and integrity_receipt.integrity_status is not IntegrityStatus.SATISFIED:
        decision = RoutingDecision(
            protocol_version=CURRENT_PROTOCOL_VERSION,
            decision_id=decision_id if decision_id is not None else _default_decision_id(
                source_digest, overlay_digest, task_dig, registry_dig,
            ),
            task_id=task.task_id,
            status=RoutingStatus.BLOCKED_BY_INTEGRITY,
            primary_family=None,
            mandatory_review_family=None,
            candidate_evaluations=(),
            reason_codes=(RoutingReasonCode.INTEGRITY_BLOCKED,),
            material_epistemic_factors=material_factors,
            integrity_status=integrity_receipt.integrity_status,
            source_artifact_digest=source_digest,
            source_overlay_digest=overlay_digest,
            task_digest=task_dig,
            registry_digest=registry_dig,
            metadata=frozen_metadata,
        )
        return decision

    effective_requirements, epistemic_reason_codes = _derive_effective_requirements(task.requirements, material_factors)

    investigative_needed = bool(effective_requirements & INVESTIGATIVE_REQUIREMENT_KINDS)
    implementation_needed = bool(effective_requirements & IMPLEMENTATION_REQUIREMENT_KINDS)
    adversarial_needed = bool(effective_requirements & _REVIEW_TRIGGER_KINDS)
    core_requirements = effective_requirements - frozenset({CognitiveRequirementKind.ADVERSARIAL_REVIEW})

    candidate_evaluations = tuple(
        _evaluate_candidate(entry, core_requirements) for entry in validated_registry
    )
    eligible_by_family = {c.family: c for c in candidate_evaluations if c.eligible}

    primary_family, preference_ignored = _select_primary(
        eligible_by_family, task.preferred_family, investigative_needed, implementation_needed,
    )

    reason_codes: set[RoutingReasonCode] = set(epistemic_reason_codes)
    mandatory_review_family: CognitiveFamily | None = None

    if adversarial_needed:
        reason_codes.add(RoutingReasonCode.ADVERSARIAL_REVIEW_REQUIRED)
        # A reviewer's eligibility is evaluated independently of the
        # PRIMARY task's core-requirement coverage (a candidate need not
        # be able to do the primary work to be a valid reviewer of it) --
        # only its own lifecycle/runtime eligibility and whether it
        # supports one of the review-triggering requirement kinds.
        aeternum_entry = next((e for e in validated_registry if e.family is CognitiveFamily.AETERNUM), None)
        if (
            aeternum_entry is not None
            and registry_module.is_eligible(aeternum_entry)
            and bool(effective_requirements & _REVIEW_TRIGGER_KINDS & aeternum_entry.supported_requirements)
        ):
            mandatory_review_family = CognitiveFamily.AETERNUM
        else:
            reason_codes.add(RoutingReasonCode.ADVERSARIAL_REVIEWER_UNAVAILABLE)

    if preference_ignored:
        reason_codes.add(RoutingReasonCode.PREFERENCE_NOT_ELIGIBLE)

    if CognitiveRequirementKind.CAUSAL_REASONING in effective_requirements:
        reason_codes.add(RoutingReasonCode.CAUSAL_INVESTIGATION_REQUIRED)
    if CognitiveRequirementKind.HIGH_CONSEQUENCE_REASONING in effective_requirements:
        reason_codes.add(RoutingReasonCode.HIGH_CONSEQUENCE_REQUIRES_REVIEW)

    if primary_family is None:
        status = RoutingStatus.NO_ELIGIBLE_ROUTE
        reason_codes.add(RoutingReasonCode.NO_CANDIDATE_ELIGIBLE)
    else:
        reason_codes.add(RoutingReasonCode.ELIGIBLE_CAPABILITY_MATCH)
        if adversarial_needed:
            status = RoutingStatus.REVIEW_REQUIRED
        elif investigative_needed and primary_family is CognitiveFamily.NOVUS:
            status = RoutingStatus.INVESTIGATION_REQUIRED
        else:
            status = RoutingStatus.SELECTED

    decision = RoutingDecision(
        protocol_version=CURRENT_PROTOCOL_VERSION,
        decision_id=decision_id if decision_id is not None else _default_decision_id(
            source_digest, overlay_digest, task_dig, registry_dig,
        ),
        task_id=task.task_id,
        status=status,
        primary_family=primary_family,
        mandatory_review_family=mandatory_review_family,
        candidate_evaluations=tuple(sorted(candidate_evaluations, key=lambda c: c.family.value)),
        reason_codes=tuple(sorted(reason_codes, key=lambda r: r.value)),
        material_epistemic_factors=material_factors,
        integrity_status=integrity_receipt.integrity_status if integrity_receipt is not None else None,
        source_artifact_digest=source_digest,
        source_overlay_digest=overlay_digest,
        task_digest=task_dig,
        registry_digest=registry_dig,
        metadata=frozen_metadata,
    )
    return decision


# ── internal helpers ────────────────────────────────────────────────────


def _validate_and_normalize_task(task: CognitiveTaskProfile) -> CognitiveTaskProfile:
    require_string(task.task_id, where="task.task_id")

    if not isinstance(task.requirements, (frozenset, set, tuple, list)):
        raise errors.InvalidObjectType(
            f"task.requirements: expected frozenset/set/tuple/list, got {type(task.requirements).__name__}"
        )
    if len(task.requirements) > MAX_REQUIREMENTS_PER_TASK:
        raise errors.PayloadLimitExceeded("task.requirements exceeds MAX_REQUIREMENTS_PER_TASK")
    for member in task.requirements:
        require_enum_member(member, CognitiveRequirementKind, where="task.requirements[]")
    normalized_requirements = frozenset(task.requirements)

    if not isinstance(task.material_epistemic_atom_ids, (tuple, list)):
        raise errors.InvalidObjectType(
            f"task.material_epistemic_atom_ids: expected tuple/list, got {type(task.material_epistemic_atom_ids).__name__}"
        )
    if len(task.material_epistemic_atom_ids) > MAX_MATERIAL_ATOMS_PER_TASK:
        raise errors.PayloadLimitExceeded("task.material_epistemic_atom_ids exceeds MAX_MATERIAL_ATOMS_PER_TASK")
    seen: set[str] = set()
    for atom_id in task.material_epistemic_atom_ids:
        require_string(atom_id, where="task.material_epistemic_atom_ids[]")
        if atom_id in seen:
            raise errors.DuplicateRequirementEntry(f"duplicate material_epistemic_atom_ids entry: {atom_id!r}")
        seen.add(atom_id)

    if task.preferred_family is not None:
        require_enum_member(task.preferred_family, CognitiveFamily, where="task.preferred_family")

    metadata_root = require_mapping_root(task.metadata, where="task.metadata")
    frozen_metadata = validate_and_freeze(metadata_root, where="task.metadata")

    return dataclasses.replace(task, requirements=normalized_requirements, metadata=frozen_metadata)


def _derive_effective_requirements(
    requirements: frozenset[CognitiveRequirementKind], material_factors: tuple[MaterialEpistemicFactor, ...],
) -> tuple[frozenset[CognitiveRequirementKind], set[RoutingReasonCode]]:
    """Epistemic state is a first-class routing signal (section 7):
    material UNCERTAIN/UNKNOWN/DISPUTED/UNVERIFIABLE premises add
    implicit requirements, never silently ignored -- and the fact that
    they did is always recorded via a reason code (Cognitive
    Conservation)."""
    effective = set(requirements)
    reasons: set[RoutingReasonCode] = set()

    for factor in material_factors:
        if factor.epistemic_state is EpistemicState.UNCERTAIN:
            effective.add(CognitiveRequirementKind.UNCERTAINTY_RESOLUTION)
            reasons.add(RoutingReasonCode.UNCERTAIN_PREMISE_REQUIRES_INVESTIGATION)
        elif factor.epistemic_state is EpistemicState.UNKNOWN:
            effective.add(CognitiveRequirementKind.INVESTIGATION)
            reasons.add(RoutingReasonCode.UNKNOWN_PREMISE_REQUIRES_INVESTIGATION)
        elif factor.epistemic_state is EpistemicState.DISPUTED:
            effective.add(CognitiveRequirementKind.CONTRADICTION_RESOLUTION)
            reasons.add(RoutingReasonCode.DISPUTED_PREMISE_REQUIRES_REVIEW)
        elif factor.epistemic_state is EpistemicState.UNVERIFIABLE:
            effective.add(CognitiveRequirementKind.UNCERTAINTY_RESOLUTION)
            reasons.add(RoutingReasonCode.UNCERTAIN_PREMISE_REQUIRES_INVESTIGATION)
        # KNOWN and INFERRED add no implicit requirement -- a
        # sufficiently established premise needs no extra caution.

    return frozenset(effective), reasons


def _evaluate_candidate(
    entry: IntelligenceCapabilityProfile, core_requirements: frozenset[CognitiveRequirementKind],
) -> RoutingCandidateEvaluation:
    rejection_reasons: list[RoutingReasonCode] = []
    if entry.runtime_availability is not entry.runtime_availability.AVAILABLE:
        rejection_reasons.append(RoutingReasonCode.RUNTIME_UNAVAILABLE)
    if entry.lifecycle_state not in registry_module.ELIGIBLE_LIFECYCLE_STATES:
        rejection_reasons.append(RoutingReasonCode.LIFECYCLE_INELIGIBLE)
    if not rejection_reasons and core_requirements and not core_requirements.issubset(entry.supported_requirements):
        rejection_reasons.append(RoutingReasonCode.CAPABILITY_ABSENT)

    return RoutingCandidateEvaluation(
        family=entry.family,
        eligible=not rejection_reasons,
        role=entry.role,
        rejection_reasons=tuple(rejection_reasons),
    )


def _select_primary(
    eligible_by_family: dict[CognitiveFamily, RoutingCandidateEvaluation],
    preferred_family: CognitiveFamily | None,
    investigative_needed: bool,
    implementation_needed: bool,
) -> tuple[CognitiveFamily | None, bool]:
    """Returns (selected_family, preference_was_ignored). Deterministic:
    a caller preference is honored ONLY if independently eligible
    (section 16 -- a preference is never capability proof); otherwise
    role-priority ordering applies, itself deterministic and never
    dependent on registry iteration/insertion order (candidates are
    evaluated from the already family-sorted registry)."""
    if preferred_family is not None:
        if preferred_family in eligible_by_family:
            return preferred_family, False
        preference_ignored = True
    else:
        preference_ignored = False

    if investigative_needed:
        priority = (CognitiveFamily.NOVUS, CognitiveFamily.GENESIS, CognitiveFamily.AETERNUM)
    elif implementation_needed:
        priority = (CognitiveFamily.GENESIS, CognitiveFamily.NOVUS, CognitiveFamily.AETERNUM)
    else:
        priority = tuple(sorted(CognitiveFamily, key=lambda f: f.value))

    for family in priority:
        if family in eligible_by_family:
            return family, preference_ignored

    return None, preference_ignored


def _canonical_json_payload(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False)


def _task_digest(task: CognitiveTaskProfile) -> str:
    from orneur.intelligence.router.canonical import _to_json_safe

    payload = {
        "task_id": task.task_id,
        "requirements": sorted(r.value for r in task.requirements),
        "material_epistemic_atom_ids": sorted(task.material_epistemic_atom_ids),
        "preferred_family": task.preferred_family.value if task.preferred_family is not None else None,
        "metadata": _to_json_safe(task.metadata),
    }
    return hashlib.sha256(_canonical_json_payload(payload).encode("utf-8")).hexdigest()


def _default_decision_id(source_digest: str, overlay_digest: str, task_digest: str, registry_digest: str) -> str:
    payload = f"routing-decision:{source_digest}:{overlay_digest}:{task_digest}:{registry_digest}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
