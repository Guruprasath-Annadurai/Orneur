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
from orneur.intelligence.integrity import errors, floor, overlay_trust
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
    IntegrityOverlayTrustContext,
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
    overlay_trust_context: IntegrityOverlayTrustContext = overlay_trust.UNTRUSTED,
    expected_overlay_digest: str | None = None,
    policy: IntegrityPolicy | None = None,
    evaluated_at: str | None = None,
    receipt_id: str | None = None,
    metadata: dict | None = None,
) -> IntegrityReceipt:
    """Deterministically evaluate `proposal` against `overlay`
    (verified-bound to `artifact` AND content-verified against a
    trusted, out-of-band `expected_overlay_digest`). Same proposal +
    same overlay + same policy + same evaluated_at => byte-identical
    canonical receipt (see canonical.digest).

    `overlay_trust_context` and `expected_overlay_digest` establish the
    OVERLAY TRUST BOUNDARY: artifact_id/artifact_digest binding
    (verify_overlay_binding, checked below) proves which OCL artifact
    the overlay CLAIMS to assess -- it does NOT prove the overlay was
    actually produced by Phase 18's assess_artifact() or that its
    EpistemicAssessments were not substituted afterward. Callers MUST
    pass `overlay_trust_context=TRUSTED_PHASE18_RUNTIME` plus the exact
    `epistemic.canonical.digest(overlay)` value computed by the trusted
    Phase-18 runtime that produced (or last validated) the overlay --
    never derived from the overlay object itself, which would prove
    nothing. The default UNTRUSTED context always fails closed: an
    UNTRUSTED overlay cannot be used as epistemic authority. This is
    content-identity verification under a trusted invocation boundary,
    NOT cryptographic provenance/authentication -- no signature scheme
    exists in this repository at any layer."""
    require_instance(overlay, EpistemicOverlay, where="overlay")
    require_instance(artifact, CognitiveArtifact, where="artifact")
    require_instance(proposal, IntegrityProposal, where="proposal")
    if policy is not None:
        require_instance(policy, IntegrityPolicy, where="policy")
        policy = floor.normalize_policy(policy)
    if evaluated_at is not None:
        require_string(evaluated_at, where="evaluated_at")
        floor.parse_aware_iso8601(evaluated_at, where="evaluated_at", error_cls=errors.InvalidStructuredValue)
    if receipt_id is not None:
        require_string(receipt_id, where="receipt_id")

    if not overlay_trust.is_valid_overlay_trust_context(overlay_trust_context):
        raise errors.InvalidOverlayTrustContext(
            f"overlay_trust_context must be a genuine IntegrityOverlayTrustContext member, "
            f"got {type(overlay_trust_context).__name__}"
        )
    if overlay_trust_context is overlay_trust.UNTRUSTED:
        raise errors.UntrustedOverlayRejected(
            "assess_integrity() requires an explicit overlay_trust_context=TRUSTED_PHASE18_RUNTIME "
            "plus a matching expected_overlay_digest -- an UNTRUSTED overlay cannot be used as "
            "epistemic authority"
        )
    require_string(expected_overlay_digest, where="expected_overlay_digest")

    try:
        verify_overlay_binding(overlay, artifact)
    except SourceArtifactMismatch as exc:
        raise errors.OverlayBindingInvalid(str(exc.detail)) from exc

    overlay_digest = epistemic_canonical.digest(overlay)
    if overlay_digest != expected_overlay_digest:
        raise errors.OverlayProvenanceInvalid(
            "overlay content digest does not match the trusted expected_overlay_digest -- the "
            "overlay's assessments may have been altered/substituted after being produced"
        )

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
    proposal_metadata = _require_mapping_root(proposal.metadata, where="proposal.metadata")
    proposal_metadata = validate_and_freeze(proposal_metadata, where="proposal.metadata")

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
        # validate_policy() above already guaranteed evaluated_at is not
        # None here, and both timestamps have already been confirmed
        # offset-aware and well-formed (evaluated_at above; overlay.assessed_at
        # is re-checked defensively inside is_overlay_stale itself).
        assert evaluated_at is not None
        if floor.is_overlay_stale(
            overlay_assessed_at=overlay.assessed_at,
            evaluated_at=evaluated_at,
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
    # overlay_digest was already computed above for the provenance
    # check -- reused here rather than recomputed.
    proposal_digest = _proposal_digest(proposal, assertions, scope_ids, proposal_metadata)
    policy_digest = _policy_digest(policy)

    receipt_metadata_root = _require_mapping_root(metadata if metadata is not None else {}, where="metadata")
    receipt_metadata = validate_and_freeze(receipt_metadata_root, where="metadata")

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
        required_disclosures=tuple(sorted(required_disclosures, key=_disclosure_sort_key)),
        violations=tuple(sorted(all_violations, key=_violation_sort_key)),
        material_scope_coverage=tuple(sorted(material_scope_coverage)),
        omitted_scope_atom_ids=tuple(sorted(omitted_scope_atom_ids)),
        integrity_status=integrity_status,
        metadata=receipt_metadata,
    )
    return receipt


def require_integrity(
    proposal: IntegrityProposal,
    *,
    overlay: EpistemicOverlay,
    artifact: CognitiveArtifact,
    overlay_trust_context: IntegrityOverlayTrustContext = overlay_trust.UNTRUSTED,
    expected_overlay_digest: str | None = None,
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
        proposal, overlay=overlay, artifact=artifact,
        overlay_trust_context=overlay_trust_context, expected_overlay_digest=expected_overlay_digest,
        policy=policy, evaluated_at=evaluated_at, receipt_id=receipt_id, metadata=metadata,
    )
    if receipt.integrity_status is not IntegrityStatus.SATISFIED:
        raise errors.IntegrityRequirementNotSatisfied(
            f"integrity_status={receipt.integrity_status.value!r} with {len(receipt.violations)} violation(s)"
        )
    return receipt


# ── internal helpers ────────────────────────────────────────────────────


def _require_mapping_root(value: object, *, where: str) -> object:
    """Metadata fields are a mapping contract at the ROOT -- a scalar
    (str/int/bool/...) must never silently pass just because
    freeze.validate_and_freeze() happens to accept scalars as valid
    NESTED values. Only dict/MappingProxyType are valid roots."""
    from types import MappingProxyType

    if not isinstance(value, (dict, MappingProxyType)):
        raise errors.InvalidObjectType(f"{where}: expected a mapping, got {type(value).__name__}")
    return value


def _validate_and_normalize_assertion(entry: object) -> ProposedAssertion:
    require_instance(entry, ProposedAssertion, where="proposal.assertions[]")
    require_string(entry.assertion_id, where="ProposedAssertion.assertion_id")
    require_string(entry.source_atom_id, where="ProposedAssertion.source_atom_id")
    require_enum_member(entry.treatment, PresentationTreatment, where="ProposedAssertion.treatment")
    if entry.asserted_polarity is not None:
        require_enum_member(entry.asserted_polarity, EpistemicPolarity, where="ProposedAssertion.asserted_polarity")
    if entry.reference is not None:
        require_string(entry.reference, where="ProposedAssertion.reference")
    metadata_root = _require_mapping_root(entry.metadata, where="ProposedAssertion.metadata")
    frozen_metadata = validate_and_freeze(metadata_root, where="ProposedAssertion.metadata")
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
    maximum = floor.effective_maximum_treatment(state, policy)
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


def _disclosure_sort_key(disclosure: DisclosureRequirement) -> tuple[str, str]:
    return (disclosure.assertion_id, disclosure.obligation.value)


def _violation_sort_key(violation: IntegrityViolation) -> tuple[str, str, str]:
    return (violation.reason.value, violation.assertion_id or "", violation.source_atom_id or "")


def _canonical_json_payload(obj: dict) -> str:
    import json

    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False)


def _metadata_to_json_safe(value: object) -> object:
    """Metadata has already passed through freeze.validate_and_freeze(),
    so it only ever contains MappingProxyType/tuple/str/int/float/bool/
    None -- no dataclasses or enums to worry about here, unlike
    canonical.py's fuller _to_json_safe()."""
    from types import MappingProxyType

    if isinstance(value, (dict, MappingProxyType)):
        return {str(k): _metadata_to_json_safe(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_metadata_to_json_safe(item) for item in value]
    return value


def _proposal_digest(
    proposal: IntegrityProposal,
    assertions: tuple[ProposedAssertion, ...],
    scope_ids: tuple[str, ...],
    proposal_metadata: object,
) -> str:
    """Binds the COMPLETE normalized structured proposal -- including
    proposal.metadata and every assertion.metadata, not just the
    semantically-load-bearing fields. Both are part of the public
    contract, so both are bound; a caller changing only metadata must
    see a different digest/default receipt_id."""
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
                    "metadata": _metadata_to_json_safe(a.metadata),
                }
                for a in assertions
            ),
            key=lambda d: d["assertion_id"],
        ),
        "required_scope_atom_ids": sorted(scope_ids),
        "metadata": _metadata_to_json_safe(proposal_metadata),
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
