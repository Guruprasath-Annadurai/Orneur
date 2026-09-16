"""
Closure: trusted overlay provenance. Reproduced defect: a real Phase-18
EpistemicOverlay's assessments could be replaced/forged (e.g.
dataclasses.replace(overlay, assessments=(forged,))) while
source_artifact_id/source_artifact_digest were left unchanged --
verify_overlay_binding() still passed (it only proves which OCL
artifact the overlay CLAIMS to assess, never that the assessment
CONTENT is genuine), so assess_integrity() consumed the forged
KNOWN/AFFIRMED assessment as if it were real Phase-18 output and
returned SATISFIED for an ESTABLISHED claim about an atom that was
actually UNKNOWN.

Fixed: assess_integrity() now requires an explicit
overlay_trust_context (IntegrityOverlayTrustContext, isinstance-checked,
never a bare string) plus an out-of-band expected_overlay_digest
supplied by the trusted caller (NEVER derived from the overlay object
being evaluated itself -- that would prove nothing). A mismatch raises
OverlayProvenanceInvalid before any EpistemicAssessment is consumed.
This is content-identity verification under a trusted invocation
boundary, NOT cryptographic provenance/authentication.
"""
from __future__ import annotations

import dataclasses

import pytest

from orneur.intelligence.epistemic import canonical as epistemic_canonical
from orneur.intelligence.epistemic.enums import EpistemicPolarity, EpistemicReasonCode, EpistemicState
from orneur.intelligence.epistemic.models import EpistemicAssessment
from orneur.intelligence.integrity import errors
from orneur.intelligence.integrity.contracts import IntegrityProposal, ProposedAssertion
from orneur.intelligence.integrity.enums import IntegrityOverlayTrustContext, IntegrityStatus, PresentationTreatment
from orneur.intelligence.integrity.evaluator import assess_integrity
from tests.integrity.conftest import (
    TRUSTED_PHASE18_RUNTIME,
    assess_integrity_trusted,
    build_known_affirmed_fixture,
    build_unknown_fixture,
)

UNTRUSTED = IntegrityOverlayTrustContext.UNTRUSTED


def _forge_assessment(overlay, *, atom_id, state, polarity):
    forged = EpistemicAssessment(
        atom_id=atom_id, state=state, polarity=polarity,
        direct_support_evidence_refs=("fake-e1",),
        reason_codes=(EpistemicReasonCode.DIRECT_VERIFIED_SUPPORT,),
    )
    return dataclasses.replace(overlay, assessments=(forged,))


def _proposal():
    return IntegrityProposal(proposal_id="p1", assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),))


# ── Section 2: reproduce, then confirm the fix ──────────────────────────


def test_forged_assessment_with_correct_artifact_binding_is_now_rejected():
    """The exact reproduction from the closure spec: source_artifact_id
    and source_artifact_digest are UNCHANGED; only the assessment
    content is forged from UNKNOWN to KNOWN/AFFIRMED. Must be rejected
    at the provenance boundary, before ESTABLISHED is ever accepted."""
    artifact, overlay = build_unknown_fixture(atom_id="a1")
    trusted_digest = epistemic_canonical.digest(overlay)  # captured from the REAL overlay, before forging
    forged_overlay = _forge_assessment(overlay, atom_id="a1", state=EpistemicState.KNOWN, polarity=EpistemicPolarity.AFFIRMED)

    assert forged_overlay.source_artifact_id == overlay.source_artifact_id
    assert forged_overlay.source_artifact_digest == overlay.source_artifact_digest
    assert forged_overlay.assessments[0].state is EpistemicState.KNOWN

    with pytest.raises(errors.OverlayProvenanceInvalid):
        assess_integrity(
            _proposal(), overlay=forged_overlay, artifact=artifact,
            overlay_trust_context=TRUSTED_PHASE18_RUNTIME, expected_overlay_digest=trusted_digest,
        )


def test_forged_assessment_would_have_been_satisfied_under_the_old_binding_only_check():
    """Documents the pre-fix behavior directly: verify_overlay_binding()
    ALONE (with no provenance check) genuinely does not detect this
    forgery -- proving the defect was real, not hypothetical."""
    from orneur.intelligence.epistemic import verify_overlay_binding

    artifact, overlay = build_unknown_fixture(atom_id="a1")
    forged_overlay = _forge_assessment(overlay, atom_id="a1", state=EpistemicState.KNOWN, polarity=EpistemicPolarity.AFFIRMED)
    verify_overlay_binding(forged_overlay, artifact)  # must NOT raise -- binding alone is insufficient


# ── Section 6: trusted fresh-production end-to-end path ─────────────────


def test_real_phase18_overlay_with_correct_trusted_digest_passes_through_normally():
    artifact, overlay = build_known_affirmed_fixture()
    trusted_digest = epistemic_canonical.digest(overlay)
    receipt = assess_integrity(
        _proposal(), overlay=overlay, artifact=artifact,
        overlay_trust_context=TRUSTED_PHASE18_RUNTIME, expected_overlay_digest=trusted_digest,
    )
    assert receipt.integrity_status is IntegrityStatus.SATISFIED


def test_mutating_assessment_after_computing_trusted_digest_is_caught():
    """The canonical end-to-end sequence: compute the trusted digest
    from the genuine overlay, THEN mutate/replace an assessment while
    preserving source_artifact_id/source_artifact_digest, THEN reuse the
    ORIGINAL trusted digest -- must fail before epistemic state is
    consumed."""
    artifact, overlay = build_known_affirmed_fixture()
    trusted_digest = epistemic_canonical.digest(overlay)  # computed BEFORE mutation

    tampered = _forge_assessment(overlay, atom_id="a1", state=EpistemicState.DISPUTED, polarity=EpistemicPolarity.MIXED)
    assert tampered.source_artifact_id == overlay.source_artifact_id
    assert tampered.source_artifact_digest == overlay.source_artifact_digest

    with pytest.raises(errors.OverlayProvenanceInvalid):
        assess_integrity(
            _proposal(), overlay=tampered, artifact=artifact,
            overlay_trust_context=TRUSTED_PHASE18_RUNTIME, expected_overlay_digest=trusted_digest,
        )


# ── Section 7: plain-string / payload self-elevation ────────────────────


def test_bare_string_trust_context_rejected():
    artifact, overlay = build_known_affirmed_fixture()
    trusted_digest = epistemic_canonical.digest(overlay)
    with pytest.raises(errors.InvalidOverlayTrustContext):
        assess_integrity(
            _proposal(), overlay=overlay, artifact=artifact,
            overlay_trust_context="TRUSTED_PHASE18_RUNTIME",  # bare str, not the enum
            expected_overlay_digest=trusted_digest,
        )


def test_untrusted_default_is_rejected_outright():
    artifact, overlay = build_known_affirmed_fixture()
    with pytest.raises(errors.UntrustedOverlayRejected):
        assess_integrity(_proposal(), overlay=overlay, artifact=artifact)  # no trust args at all


def test_untrusted_explicit_is_rejected_outright():
    artifact, overlay = build_known_affirmed_fixture()
    trusted_digest = epistemic_canonical.digest(overlay)
    with pytest.raises(errors.UntrustedOverlayRejected):
        assess_integrity(
            _proposal(), overlay=overlay, artifact=artifact,
            overlay_trust_context=UNTRUSTED, expected_overlay_digest=trusted_digest,
        )


def test_overlay_metadata_self_claiming_trusted_has_no_effect():
    """overlay.metadata={"trusted": True} must never be read as a trust
    signal -- trust comes ONLY from the explicit out-of-band
    overlay_trust_context argument."""
    artifact, overlay = build_unknown_fixture(atom_id="a1")
    self_claiming = dataclasses.replace(overlay, metadata={"trusted": True, "verified_overlay": True})
    # Without a real trust context, still rejected regardless of the
    # self-claiming metadata.
    with pytest.raises(errors.UntrustedOverlayRejected):
        assess_integrity(_proposal(), overlay=self_claiming, artifact=artifact)


def test_proposal_metadata_self_claiming_overlay_trust_has_no_effect():
    """proposal.metadata={"overlay_trust": "TRUSTED_PHASE18_RUNTIME"} must
    never be read as a trust signal either -- there is no code path in
    the evaluator that inspects proposal.metadata to decide trust."""
    artifact, overlay = build_unknown_fixture(atom_id="a1")
    proposal = IntegrityProposal(
        proposal_id="p1",
        assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),),
        metadata={"overlay_trust": "TRUSTED_PHASE18_RUNTIME", "verified_overlay": True},
    )
    with pytest.raises(errors.UntrustedOverlayRejected):
        assess_integrity(proposal, overlay=overlay, artifact=artifact)  # no real trust args supplied


# ── Section 8: malformed overlay structure (defense-in-depth) ───────────


def test_untrusted_malformed_overlay_rejected_at_trust_boundary_first():
    """Under UNTRUSTED, rejection happens at the trust boundary --
    before Phase 19 ever inspects assessment content, malformed or not."""
    artifact, overlay = build_unknown_fixture(atom_id="a1")
    malformed = dataclasses.replace(
        overlay,
        assessments=(dataclasses.replace(overlay.assessments[0], state=EpistemicState.KNOWN),),
    )
    with pytest.raises(errors.UntrustedOverlayRejected):
        assess_integrity(_proposal(), overlay=malformed, artifact=artifact)


def test_trusted_context_wrong_expected_digest_rejects_malformed_overlay_too():
    """Under a TRUSTED context but a mismatched expected digest, a
    structurally-malformed overlay is rejected by the digest check --
    Phase 19 never attempts to recompute epistemic truth from a
    malformed structure."""
    artifact, overlay = build_unknown_fixture(atom_id="a1")
    duplicated = dataclasses.replace(
        overlay,
        assessments=overlay.assessments + overlay.assessments,  # duplicate atom_id assessments
    )
    with pytest.raises(errors.OverlayProvenanceInvalid):
        assess_integrity(
            _proposal(), overlay=duplicated, artifact=artifact,
            overlay_trust_context=TRUSTED_PHASE18_RUNTIME,
            expected_overlay_digest=epistemic_canonical.digest(overlay),  # digest of the ORIGINAL, not the duplicated one
        )


def test_no_raw_exception_leakage_from_forged_or_malformed_overlay_paths():
    artifact, overlay = build_unknown_fixture(atom_id="a1")
    forged_overlay = _forge_assessment(overlay, atom_id="a1", state=EpistemicState.KNOWN, polarity=EpistemicPolarity.AFFIRMED)
    trusted_digest = epistemic_canonical.digest(overlay)
    try:
        assess_integrity(
            _proposal(), overlay=forged_overlay, artifact=artifact,
            overlay_trust_context=TRUSTED_PHASE18_RUNTIME, expected_overlay_digest=trusted_digest,
        )
        assert False, "expected an exception"
    except errors.IntegrityError:
        pass
    except (AttributeError, TypeError, KeyError, ValueError) as exc:
        pytest.fail(f"a raw {type(exc).__name__} escaped instead of a typed IntegrityError: {exc}")


def test_assess_integrity_trusted_conftest_helper_still_works_for_ordinary_tests():
    """Sanity check on the test convenience wrapper itself: it correctly
    trusts an un-tampered, freshly-built overlay."""
    artifact, overlay = build_known_affirmed_fixture()
    receipt = assess_integrity_trusted(_proposal(), overlay=overlay, artifact=artifact)
    assert receipt.integrity_status is IntegrityStatus.SATISFIED
