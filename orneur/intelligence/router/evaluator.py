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
from orneur.intelligence.router import errors, receipt_trust, registry as registry_module
from orneur.intelligence.router.contracts import (
    CognitiveTaskProfile,
    IntelligenceCapabilityProfile,
    MaterialEpistemicFactor,
    RoutingCandidateEvaluation,
    RoutingDecision,
)
from orneur.intelligence.router.enums import (
    CURRENT_PROTOCOL_VERSION,
    DISCOVERY_REQUIREMENT_KINDS,
    IMPLEMENTATION_REQUIREMENT_KINDS,
    INVESTIGATIVE_REQUIREMENT_KINDS,
    CapabilityRegistryTrustContext,
    CognitiveFamily,
    CognitiveRequirementKind,
    CognitiveRole,
    IntegrityReceiptTrustContext,
    RoutingReasonCode,
    RoutingStatus,
)
from orneur.intelligence.router.freeze import require_mapping_root, validate_and_freeze
from orneur.intelligence.router.limits import MAX_MATERIAL_ATOMS_PER_TASK, MAX_REQUIREMENTS_PER_TASK
from orneur.intelligence.router.typecheck import require_enum_member, require_instance, require_string

_NO_RECEIPT_DIGEST_SENTINEL = "NONE"

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
    integrity_receipt_trust_context: IntegrityReceiptTrustContext = receipt_trust.UNTRUSTED,
    expected_integrity_receipt_digest: str | None = None,
    capability_registry: tuple[IntelligenceCapabilityProfile, ...] | None = None,
    capability_registry_trust_context: CapabilityRegistryTrustContext = registry_module.UNTRUSTED,
    expected_registry_digest: str | None = None,
    decision_id: str | None = None,
    metadata: dict | None = None,
) -> RoutingDecision:
    """Deterministically route `task` given a trusted `overlay`
    (verified via the REUSED Phase-19 `overlay_trust.verify_trusted_overlay`
    seam), a trusted `integrity_receipt` if supplied (verified via
    `receipt_trust.verify_trusted_receipt` + a binding check against
    THIS artifact/overlay), and a trusted `capability_registry` if
    supplied (verified via `registry.verify_trusted_registry`) --
    `capability_registry=None` uses the code-defined default registry,
    trusted by construction. This function never derives an "expected"
    digest for any of these three inputs from the input itself -- every
    expected digest is caller-supplied, out-of-band. Same task + same
    overlay + same integrity_receipt (or lack thereof) + same registry
    => byte-identical canonical decision (see canonical.digest)."""
    require_instance(task, CognitiveTaskProfile, where="task")
    require_instance(overlay, EpistemicOverlay, where="overlay")
    require_instance(artifact, CognitiveArtifact, where="artifact")
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

    if capability_registry is None:
        # Code-defined default: trusted by construction, no out-of-band
        # digest needed.
        validated_registry = registry_module.build_default_capability_registry()
    else:
        validated_registry = registry_module.verify_trusted_registry(
            capability_registry,
            trust_context=capability_registry_trust_context,
            expected_registry_digest=expected_registry_digest,
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

    # A supplied IntegrityReceipt is Phase-19 output -- isinstance()
    # alone proves nothing about genuine provenance. Verify provenance
    # (out-of-band expected digest), THEN structural validity, THEN
    # that the receipt actually corresponds to the CURRENT
    # artifact/overlay being routed -- all strictly before
    # `receipt.integrity_status` is ever consumed. A receipt bound to
    # a different artifact/overlay must never influence this route.
    receipt_digest_for_decision: str | None = None
    if integrity_receipt is not None:
        # verify_trusted_receipt() performs its OWN full structural
        # pre-validation (every nested AssertionAssessment/
        # DisclosureRequirement/IntegrityViolation record) before ever
        # computing/comparing a digest -- see receipt_trust.py's module
        # docstring for the exact required order. Only binding to THIS
        # artifact/overlay remains this function's responsibility.
        receipt_digest_for_decision = receipt_trust.verify_trusted_receipt(
            integrity_receipt,
            trust_context=integrity_receipt_trust_context,
            expected_receipt_digest=expected_integrity_receipt_digest,
        )
        _validate_receipt_binding(
            integrity_receipt, artifact=artifact, source_artifact_digest=source_digest, source_overlay_digest=overlay_digest,
        )

    # Integrity failure blocks routing outright -- an integrity-blocked
    # input is never routed as if it were clean, and Cognitive
    # Conservation still applies: material epistemic factors remain
    # represented even on the blocked path.
    if integrity_receipt is not None and integrity_receipt.integrity_status is not IntegrityStatus.SATISFIED:
        decision = RoutingDecision(
            protocol_version=CURRENT_PROTOCOL_VERSION,
            decision_id=decision_id if decision_id is not None else _default_decision_id(
                source_digest, overlay_digest, task_dig, registry_dig, receipt_digest_for_decision,
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
            source_integrity_receipt_digest=receipt_digest_for_decision,
            task_digest=task_dig,
            registry_digest=registry_dig,
            metadata=frozen_metadata,
        )
        return decision

    effective_requirements, epistemic_reason_codes = _derive_effective_requirements(task.requirements, material_factors)

    # A task with no explicit AND no epistemically-derived cognitive
    # requirement establishes no adequacy signal at all -- selecting an
    # "available" family in that void would be an arbitrary choice
    # dressed up as a capability match. Fail closed instead.
    if not effective_requirements:
        decision = RoutingDecision(
            protocol_version=CURRENT_PROTOCOL_VERSION,
            decision_id=decision_id if decision_id is not None else _default_decision_id(
                source_digest, overlay_digest, task_dig, registry_dig, receipt_digest_for_decision,
            ),
            task_id=task.task_id,
            status=RoutingStatus.NO_ELIGIBLE_ROUTE,
            primary_family=None,
            mandatory_review_family=None,
            candidate_evaluations=(),
            reason_codes=(RoutingReasonCode.NO_COGNITIVE_REQUIREMENT,),
            material_epistemic_factors=material_factors,
            integrity_status=integrity_receipt.integrity_status if integrity_receipt is not None else None,
            source_artifact_digest=source_digest,
            source_overlay_digest=overlay_digest,
            source_integrity_receipt_digest=receipt_digest_for_decision,
            task_digest=task_dig,
            registry_digest=registry_dig,
            metadata=frozen_metadata,
        )
        return decision

    investigative_needed = bool(effective_requirements & INVESTIGATIVE_REQUIREMENT_KINDS)
    implementation_needed = bool(effective_requirements & IMPLEMENTATION_REQUIREMENT_KINDS)
    discovery_needed = bool(effective_requirements & DISCOVERY_REQUIREMENT_KINDS)
    adversarial_needed = bool(effective_requirements & _REVIEW_TRIGGER_KINDS)

    # A task whose ENTIRE effective cognitive work is review/adversarial
    # requirement kinds IS review, not a primary task that additionally
    # needs an independent reviewer -- the distinction determines both
    # the preferred primary role and whether ADVERSARIAL_REVIEW itself
    # counts toward the primary candidate's own capability adequacy.
    review_only_task = bool(effective_requirements) and effective_requirements.issubset(_REVIEW_TRIGGER_KINDS)

    preferred_role = _derive_preferred_role(
        investigative_needed=investigative_needed, implementation_needed=implementation_needed,
        discovery_needed=discovery_needed, review_only_task=review_only_task,
    )

    core_requirements = (
        effective_requirements if review_only_task
        else effective_requirements - frozenset({CognitiveRequirementKind.ADVERSARIAL_REVIEW})
    )

    candidate_evaluations = tuple(
        _evaluate_candidate(entry, core_requirements) for entry in validated_registry
    )
    eligible_by_family = {c.family: c for c in candidate_evaluations if c.eligible}

    primary_family, preference_ignored, role_adequacy_failed = _select_primary(
        eligible_by_family, task.preferred_family, preferred_role,
    )

    reason_codes: set[RoutingReasonCode] = set(epistemic_reason_codes)
    mandatory_review_family: CognitiveFamily | None = None

    if adversarial_needed:
        reason_codes.add(RoutingReasonCode.ADVERSARIAL_REVIEW_REQUIRED)

    if adversarial_needed and not review_only_task:
        # A mixed task (primary work + a distinct mandatory-review
        # slot): the reviewer is selected by ROLE
        # (CRITIC_ARBITER_DISCOVERER), never by the literal family name
        # "AETERNUM" -- a candidate need not be able to do the primary
        # work to be a valid reviewer of it, only its own lifecycle/
        # runtime eligibility and review-capability support matter.
        eligible_critics = sorted(
            (
                entry for entry in validated_registry
                if entry.role is CognitiveRole.CRITIC_ARBITER_DISCOVERER
                and registry_module.is_eligible(entry)
                and bool(effective_requirements & _REVIEW_TRIGGER_KINDS & entry.supported_requirements)
            ),
            key=lambda e: e.family.value,
        )
        distinct_critics = [e for e in eligible_critics if e.family != primary_family]
        if distinct_critics:
            mandatory_review_family = distinct_critics[0].family
        elif eligible_critics:
            # An eligible reviewer exists but coincides with the
            # primary family -- never report a structure that
            # ambiguously implies a family independently reviewed its
            # own primary work.
            reason_codes.add(RoutingReasonCode.MANDATORY_REVIEWER_CANNOT_BE_PRIMARY_FAMILY)
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
        if role_adequacy_failed:
            reason_codes.add(RoutingReasonCode.ROLE_ADEQUACY_NOT_SATISFIED)
        else:
            reason_codes.add(RoutingReasonCode.NO_CANDIDATE_ELIGIBLE)
        if review_only_task:
            # The task itself IS review: no eligible critic means no
            # reviewing capacity exists at all -- say so explicitly,
            # not just "no candidate eligible" in the abstract.
            reason_codes.add(RoutingReasonCode.ADVERSARIAL_REVIEWER_UNAVAILABLE)
    else:
        # By construction (_select_primary only ever returns a
        # candidate whose role equals preferred_role), primary_family's
        # role always matches the task shape here -- no further
        # family-name inspection is needed to decide status semantics.
        reason_codes.add(RoutingReasonCode.ELIGIBLE_CAPABILITY_MATCH)
        if adversarial_needed and not review_only_task:
            status = RoutingStatus.REVIEW_REQUIRED
        elif investigative_needed:
            status = RoutingStatus.INVESTIGATION_REQUIRED
        else:
            status = RoutingStatus.SELECTED

    decision = RoutingDecision(
        protocol_version=CURRENT_PROTOCOL_VERSION,
        decision_id=decision_id if decision_id is not None else _default_decision_id(
            source_digest, overlay_digest, task_dig, registry_dig, receipt_digest_for_decision,
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
        source_integrity_receipt_digest=receipt_digest_for_decision,
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


def _derive_preferred_role(
    *, investigative_needed: bool, implementation_needed: bool, discovery_needed: bool, review_only_task: bool,
) -> CognitiveRole | None:
    """Cognitive ROLE, never a family name, drives primary selection.
    Fixed, documented precedence for a mixed task touching more than
    one shape (smallest conservative V1 rule): investigative work takes
    priority over implementation, which takes priority over primary
    discovery work, which takes priority over a review-only task shape.
    This precedence order is a full partition of every
    CognitiveRequirementKind (INVESTIGATIVE_REQUIREMENT_KINDS(6) +
    IMPLEMENTATION_REQUIREMENT_KINDS(3) + DISCOVERY_REQUIREMENT_KINDS(1)
    + the three review-trigger kinds = 13), so given a non-empty
    effective_requirements set (the caller already fails closed to
    NO_COGNITIVE_REQUIREMENT otherwise) this never returns None in
    practice -- None is kept only as an explicit, fail-closed default."""
    if investigative_needed:
        return CognitiveRole.REASONER_INVESTIGATOR
    if implementation_needed:
        return CognitiveRole.BUILDER_EXECUTOR
    if discovery_needed:
        return CognitiveRole.CRITIC_ARBITER_DISCOVERER
    if review_only_task:
        return CognitiveRole.CRITIC_ARBITER_DISCOVERER
    return None


def _select_primary(
    eligible_by_family: dict[CognitiveFamily, RoutingCandidateEvaluation],
    preferred_family: CognitiveFamily | None,
    preferred_role: CognitiveRole | None,
) -> tuple[CognitiveFamily | None, bool, bool]:
    """Returns (selected_family, preference_was_ignored, role_adequacy_failed).
    Deterministic: a caller preference is honored ONLY if independently
    eligible AND its role matches `preferred_role` (section 3/6 -- a
    preference can never bypass role adequacy); otherwise, among
    eligible candidates whose role equals `preferred_role`, the
    smallest family.value wins (a stable, documented, family-name-free
    tie-break -- never a hardcoded family-priority list).
    `role_adequacy_failed` is True when eligible candidates exist but
    NONE of them has the required role -- this is never silently
    treated as a match; the caller fails closed to NO_ELIGIBLE_ROUTE
    with a dedicated ROLE_ADEQUACY_NOT_SATISFIED reason instead."""
    role_matched = {family: c for family, c in eligible_by_family.items() if c.role is preferred_role}

    preference_ignored = False
    if preferred_family is not None:
        preferred_candidate = eligible_by_family.get(preferred_family)
        if preferred_candidate is not None and preferred_candidate.role is preferred_role:
            return preferred_family, False, False
        preference_ignored = True

    if role_matched:
        selected = min(role_matched, key=lambda f: f.value)
        return selected, preference_ignored, False

    role_adequacy_failed = bool(eligible_by_family) and preferred_role is not None
    return None, preference_ignored, role_adequacy_failed


def _validate_receipt_binding(
    receipt: IntegrityReceipt, *, artifact: CognitiveArtifact, source_artifact_digest: str, source_overlay_digest: str,
) -> None:
    """A provenance-verified, structurally-valid receipt can still be a
    genuine receipt for a DIFFERENT artifact/overlay pair. Binding must
    be checked BEFORE `receipt.integrity_status` is ever consumed --
    otherwise a receipt for unrelated cognitive work could incorrectly
    block (or incorrectly clear) the route being computed here."""
    if (
        receipt.source_artifact_id != artifact.artifact_id
        or receipt.source_artifact_digest != source_artifact_digest
        or receipt.source_overlay_digest != source_overlay_digest
    ):
        raise errors.IntegrityReceiptBindingInvalid(
            "integrity_receipt's source_artifact_id/source_artifact_digest/source_overlay_digest "
            "does not correspond to the artifact/overlay currently being routed"
        )


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


def _default_decision_id(
    source_digest: str, overlay_digest: str, task_digest: str, registry_digest: str, receipt_digest: str | None,
) -> str:
    receipt_component = receipt_digest if receipt_digest is not None else _NO_RECEIPT_DIGEST_SENTINEL
    payload = f"routing-decision:{source_digest}:{overlay_digest}:{task_digest}:{registry_digest}:{receipt_component}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
