"""
Phase 19 deterministic evaluator: the single place an IntegrityReceipt
is computed. See docs/orneur/phase-19/PHASE19_EPISTEMIC_INTEGRITY_SPEC.md
for the full normative matrix.

Hard invariant: this module never calls a model, a tool, the router, or
any network endpoint. It is pure deterministic code over already-trusted
Phase 18 data (a verified-bound EpistemicOverlay) and untrusted Phase 19
input (an IntegrityProposal) -- exactly mirroring the OCL-compiler /
Phase-18-resolver boundary discipline one layer up.

Structured contracts only: this module validates a STRUCTURED proposed
assertion contract against a trusted overlay. It does not parse, scan,
or semantically interpret arbitrary natural-language prose -- see
PHASE19_EPISTEMIC_INTEGRITY_SPEC.md's "Non-goals" section.
"""
from __future__ import annotations

import dataclasses
import hashlib

from orneur.intelligence.epistemic import EpistemicOverlay, EpistemicPolarity, EpistemicState, verify_overlay_binding
from orneur.intelligence.epistemic import canonical as epistemic_canonical
from orneur.intelligence.epistemic.errors import SourceArtifactMismatch
from orneur.intelligence.integrity import errors, floor
from orneur.intelligence.integrity.freeze import validate_and_freeze
from orneur.intelligence.integrity.typecheck import require_enum_member, require_instance, require_sequence_container, require_string
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
    IntegrityStatus,
    IntegrityViolationReason,
    PresentationTreatment,
)
from orneur.intelligence.integrity.limits import MAX_ASSERTIONS_PER_PROPOSAL, MAX_SCOPE_ATOMS
from orneur.intelligence.ocl.artifact import CognitiveArtifact
from orneur.intelligence.ocl import canonical as ocl_canonical

_ESTABLISHED = PresentationTreatment.ESTABLISHED
_INFERENCE = PresentationTreatment.INFERENCE
_UNCERTAIN = PresentationTreatment.UNCERTAIN
_DISPUTE = PresentationTreatment.DISPUTE
_UNKNOWN_TREATMENT = PresentationTreatment.UNKNOWN
_UNVERIFIABLE_TREATMENT = PresentationTreatment.UNVERIFIABLE
_ABSTAIN = PresentationTreatment.ABSTAIN

_POLARITY_REQUIRED_TREATMENTS = frozenset({_ESTABLISHED, _INFERENCE})


def assess_integrity(
    proposal: IntegrityProposal,
    *,
    overlay: EpistemicOverlay,
    artifact: CognitiveArtifact,
    policy: IntegrityPolicy | None = None,
    evaluated_at: str | None = None,
    receipt_id: str | None = None,
    metadata: dict | None = None,
) -> IntegrityReceipt:
    """Deterministically evaluate `proposal` against `overlay`
    (verified-bound to `artifact`). Same proposal + same overlay + same
    policy + same evaluated_at => byte-identical canonical receipt (see
    canonical.digest)."""
    require_instance(overlay, EpistemicOverlay, where="overlay")
    require_instance(artifact, CognitiveArtifact, where="artifact")
    require_instance(proposal, IntegrityProposal, where="proposal")
    if policy is not None:
        require_instance(policy, IntegrityPolicy, where="policy")
    if evaluated_at is not None:
        require_string(evaluated_at, where="evaluated_at")
        _validate_iso8601(evaluated_at, where="evaluated_at")

    try:
        verify_overlay_binding(overlay, artifact)
    except SourceArtifactMismatch as exc:
        raise errors.OverlayBindingInvalid(str(exc.detail)) from exc

    if policy is not None:
        floor.validate_policy(policy, evaluated_at=evaluated_at)

    require_string(proposal.proposal_id, where="proposal.proposal_id")
    assertions = require_sequence_container(proposal.assertions, where="proposal.assertions")
    scope_ids = require_sequence_container(proposal.required_scope_atom_ids, where="proposal.required_scope_atom_ids")
    if len(assertions) > MAX_ASSERTIONS_PER_PROPOSAL:
        raise errors.PayloadLimitExceeded("proposal.assertions exceeds MAX_ASSERTIONS_PER_PROPOSAL")
    if len(scope_ids) > MAX_SCOPE_ATOMS:
        raise errors.PayloadLimitExceeded("proposal.required_scope_atom_ids exceeds MAX_SCOPE_ATOMS")

    assertions = tuple(_validate_and_normalize_assertion(a) for a in assertions)
    _reject_duplicate_assertion_ids(assertions)
    _reject_duplicate_scope_atoms(scope_ids)

    assessments_by_atom = {a.atom_id: a for a in overlay.assessments}

    for assertion in assertions:
        if assertion.source_atom_id not in assessments_by_atom:
            raise errors.NonAssessedAtomReference(
                f"assertion {assertion.assertion_id!r} references atom_id {assertion.source_atom_id!r}, "
                f"which the supplied overlay never assessed"
            )
    for scope_atom_id in scope_ids:
        if scope_atom_id not in assessments_by_atom:
            raise errors.NonAssessedAtomReference(
                f"required_scope_atom_ids contains {scope_atom_id!r}, which the supplied overlay never assessed"
            )

    assertion_assessments = tuple(
        _assess_one_assertion(assertion, assessments_by_atom[assertion.source_atom_id], policy)
        for assertion in assertions
    )

    proposal_violations: list[IntegrityViolation] = []

    covered_atom_ids = {a.source_atom_id for a in assertions}
    material_scope_coverage: list[str] = []
    omitted_scope_atom_ids: list[str] = []
    for scope_atom_id in scope_ids:
        assessment = assessments_by_atom[scope_atom_id]
        if scope_atom_id in covered_atom_ids:
            material_scope_coverage.append(scope_atom_id)
        else:
            omitted_scope_atom_ids.append(scope_atom_id)
            if assessment.state in floor.MATERIAL_CONSERVATION_STATES:
                proposal_violations.append(
                    IntegrityViolation(
                        reason=IntegrityViolationReason.REQUIRED_SCOPE_ATOM_OMITTED,
                        assertion_id=None,
                        source_atom_id=scope_atom_id,
                        detail=f"material atom {scope_atom_id!r} ({assessment.state.value}) has no assertion in the proposal",
                    )
                )

    if policy is not None and policy.max_overlay_age_seconds is not None:
        # validate_policy() above already guaranteed evaluated_at is not None here.
        if floor.is_overlay_stale(
            overlay_assessed_at=overlay.assessed_at,
            evaluated_at=evaluated_at,  # type: ignore[arg-type]
            max_overlay_age_seconds=policy.max_overlay_age_seconds,
        ):
            proposal_violations.append(
                IntegrityViolation(
                    reason=IntegrityViolationReason.STALE_EPISTEMIC_OVERLAY,
                    assertion_id=None,
                    source_atom_id=None,
                    detail=f"overlay.assessed_at={overlay.assessed_at!r} exceeds policy.max_overlay_age_seconds "
                           f"relative to evaluated_at={evaluated_at!r}",
                )
            )

    required_disclosures = tuple(
        DisclosureRequirement(
            assertion_id=assessment.assertion_id,
            source_atom_id=assessment.source_atom_id,
            epistemic_state=assessment.epistemic_state,
            obligation=obligation,
        )
        for assessment in assertion_assessments
        for obligation in assessment.obligations
    )

    all_violations = tuple(proposal_violations) + tuple(
        IntegrityViolation(
            reason=reason,
            assertion_id=assessment.assertion_id,
            source_atom_id=assessment.source_atom_id,
            detail=f"assertion {assessment.assertion_id!r} treatment={assessment.proposed_treatment.value!r} "
                   f"vs state={assessment.epistemic_state.value!r} polarity={assessment.epistemic_polarity.value!r}",
        )
        for assessment in assertion_assessments
        for reason in assessment.violation_reasons
    )

    integrity_status = _classify_status(all_violations)

    source_digest = ocl_canonical.digest(artifact)
    overlay_digest = epistemic_canonical.digest(overlay)
    proposal_digest = _proposal_digest(proposal, assertions, scope_ids)
    policy_digest = _policy_digest(policy)

    receipt = IntegrityReceipt(
        protocol_version=CURRENT_PROTOCOL_VERSION,
        receipt_id=receipt_id if receipt_id is not None else _default_receipt_id(
            source_digest=source_digest, overlay_digest=overlay_digest,
            proposal_digest=proposal_digest, policy_digest=policy_digest, evaluated_at=evaluated_at,
        ),
        source_artifact_id=artifact.artifact_id,
        source_artifact_digest=source_digest,
        source_overlay_digest=overlay_digest,
        proposal_digest=proposal_digest,
        policy_digest=policy_digest,
        evaluated_at=evaluated_at,
        assertion_assessments=tuple(sorted(assertion_assessments, key=lambda a: a.assertion_id)),
        required_disclosures=required_disclosures,
        violations=all_violations,
        material_scope_coverage=tuple(sorted(material_scope_coverage)),
        omitted_scope_atom_ids=tuple(sorted(omitted_scope_atom_ids)),
        integrity_status=integrity_status,
        metadata=validate_and_freeze(metadata or {}, where="metadata"),
    )
    return receipt


def require_integrity(
    proposal: IntegrityProposal,
    *,
    overlay: EpistemicOverlay,
    artifact: CognitiveArtifact,
    policy: IntegrityPolicy | None = None,
    evaluated_at: str | None = None,
    receipt_id: str | None = None,
    metadata: dict | None = None,
) -> IntegrityReceipt:
    """Same as assess_integrity(), but raises
    IntegrityRequirementNotSatisfied when the resulting receipt's
    integrity_status is not SATISFIED, instead of returning a receipt
    the caller must remember to check."""
    receipt = assess_integrity(
        proposal, overlay=overlay, artifact=artifact, policy=policy,
        evaluated_at=evaluated_at, receipt_id=receipt_id, metadata=metadata,
    )
    if receipt.integrity_status is not IntegrityStatus.SATISFIED:
        raise errors.IntegrityRequirementNotSatisfied(
            f"integrity_status={receipt.integrity_status.value!r} with {len(receipt.violations)} violation(s)"
        )
    return receipt


# ── internal helpers ────────────────────────────────────────────────────


def _validate_iso8601(value: str, *, where: str) -> None:
    import datetime

    try:
        datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise errors.InvalidStructuredValue(f"{where} is not a valid ISO-8601 timestamp: {exc}") from exc


def _validate_and_normalize_assertion(entry: object) -> ProposedAssertion:
    require_instance(entry, ProposedAssertion, where="proposal.assertions[]")
    require_string(entry.assertion_id, where="ProposedAssertion.assertion_id")
    require_string(entry.source_atom_id, where="ProposedAssertion.source_atom_id")
    require_enum_member(entry.treatment, PresentationTreatment, where="ProposedAssertion.treatment")
    if entry.asserted_polarity is not None:
        require_enum_member(entry.asserted_polarity, EpistemicPolarity, where="ProposedAssertion.asserted_polarity")
    if entry.reference is not None:
        require_string(entry.reference, where="ProposedAssertion.reference")
    frozen_metadata = validate_and_freeze(entry.metadata, where="ProposedAssertion.metadata")
    return dataclasses.replace(entry, metadata=frozen_metadata)


def _reject_duplicate_assertion_ids(assertions: tuple[ProposedAssertion, ...]) -> None:
    seen: set[str] = set()
    for assertion in assertions:
        if assertion.assertion_id in seen:
            raise errors.DuplicateAssertionId(f"duplicate assertion_id: {assertion.assertion_id!r}")
        seen.add(assertion.assertion_id)


def _reject_duplicate_scope_atoms(scope_ids: tuple[str, ...]) -> None:
    seen: set[str] = set()
    for scope_atom_id in scope_ids:
        require_string(scope_atom_id, where="proposal.required_scope_atom_ids[]")
        if scope_atom_id in seen:
            raise errors.DuplicateScopeAtom(f"duplicate required_scope_atom_ids entry: {scope_atom_id!r}")
        seen.add(scope_atom_id)


def _classify_violation_reason(state: EpistemicState, treatment: PresentationTreatment) -> IntegrityViolationReason:
    if state is EpistemicState.INFERRED and treatment is _ESTABLISHED:
        return IntegrityViolationReason.INFERENCE_PRESENTED_AS_FACT
    if state is EpistemicState.UNCERTAIN and treatment in (_ESTABLISHED, _INFERENCE):
        return IntegrityViolationReason.UNCERTAINTY_SUPPRESSED
    if state is EpistemicState.DISPUTED and treatment in (_ESTABLISHED, _INFERENCE):
        return IntegrityViolationReason.DISPUTE_SUPPRESSED
    if state is EpistemicState.UNKNOWN:
        return IntegrityViolationReason.UNKNOWN_PRESENTED_AS_KNOWLEDGE
    if state is EpistemicState.UNVERIFIABLE:
        return IntegrityViolationReason.UNVERIFIABLE_PRESENTED_AS_VERIFIED
    return IntegrityViolationReason.PRESENTED_STRONGER_THAN_STATE


def _assess_one_assertion(
    assertion: ProposedAssertion, assessment, policy: IntegrityPolicy | None,
) -> AssertionAssessment:
    state = assessment.state
    polarity = assessment.polarity
    permitted = floor.effective_permitted_treatments(state, policy)
    maximum = floor.HARD_FLOOR_MAXIMUM_TREATMENT[state]
    obligation = floor.STATE_REQUIRED_OBLIGATION[state]
    obligations = (obligation,) if obligation is not None else ()

    violation_reasons: list[IntegrityViolationReason] = []

    if assertion.treatment not in permitted:
        violation_reasons.append(_classify_violation_reason(state, assertion.treatment))
    elif assertion.treatment in _POLARITY_REQUIRED_TREATMENTS:
        if assertion.asserted_polarity is None or assertion.asserted_polarity is not polarity:
            violation_reasons.append(IntegrityViolationReason.POLARITY_MISMATCH)

    return AssertionAssessment(
        assertion_id=assertion.assertion_id,
        source_atom_id=assertion.source_atom_id,
        epistemic_state=state,
        epistemic_polarity=polarity,
        proposed_treatment=assertion.treatment,
        permitted_maximum_treatment=maximum,
        obligations=obligations,
        violation_reasons=tuple(violation_reasons),
        satisfied=not violation_reasons,
    )


def _classify_status(violations: tuple[IntegrityViolation, ...]) -> IntegrityStatus:
    if not violations:
        return IntegrityStatus.SATISFIED
    if any(v.reason in BLOCKING_VIOLATION_REASONS for v in violations):
        return IntegrityStatus.BLOCKED
    return IntegrityStatus.REQUIRES_REVISION


def _canonical_json_payload(obj: dict) -> str:
    import json

    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False)


def _proposal_digest(proposal: IntegrityProposal, assertions: tuple[ProposedAssertion, ...], scope_ids: tuple[str, ...]) -> str:
    payload = {
        "proposal_id": proposal.proposal_id,
        "assertions": sorted(
            (
                {
                    "assertion_id": a.assertion_id,
                    "source_atom_id": a.source_atom_id,
                    "treatment": a.treatment.value,
                    "asserted_polarity": a.asserted_polarity.value if a.asserted_polarity is not None else None,
                    "reference": a.reference,
                }
                for a in assertions
            ),
            key=lambda d: d["assertion_id"],
        ),
        "required_scope_atom_ids": sorted(scope_ids),
    }
    return hashlib.sha256(_canonical_json_payload(payload).encode("utf-8")).hexdigest()


def _policy_digest(policy: IntegrityPolicy | None) -> str:
    if policy is None:
        payload = {"policy": None}
    else:
        payload = {
            "stricter_permitted_treatments": sorted(
                (
                    {"state": state.value, "treatments": sorted(t.value for t in treatments)}
                    for state, treatments in policy.stricter_permitted_treatments.items()
                ),
                key=lambda d: d["state"],
            ),
            "max_overlay_age_seconds": policy.max_overlay_age_seconds,
        }
    return hashlib.sha256(_canonical_json_payload(payload).encode("utf-8")).hexdigest()


def _default_receipt_id(*, source_digest: str, overlay_digest: str, proposal_digest: str, policy_digest: str, evaluated_at: str | None) -> str:
    payload = f"integrity-receipt:{source_digest}:{overlay_digest}:{proposal_digest}:{policy_digest}:{evaluated_at or ''}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
