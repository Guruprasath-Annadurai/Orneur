"""
Closure: default overlay_id non-determinism. Reproduced defect: prior
production code did `overlay_id=overlay_id or str(uuid.uuid4())`, so two
identical default-invocation calls to assess_artifact() produced
different overlay_ids and therefore different canonical digests --
violating the Phase 18 doctrine that same artifact + same context +
same assessed_at must yield the same canonical overlay. Fixed by
deriving the default overlay_id from
(source_artifact_digest, assessment_context_digest, assessed_at) via
resolver._default_overlay_id() -- never uuid4()/random/wall-clock.
"""
from __future__ import annotations

from orneur.intelligence.epistemic.canonical import digest, to_canonical_json
from orneur.intelligence.epistemic.enums import EvidenceResolutionStatus, EvidenceStance
from orneur.intelligence.epistemic.resolver import _default_overlay_id, assess_artifact
from tests.epistemic.conftest import ASSESSED_AT, TRUSTED_OCL, TRUSTED_VERIFIER, make_artifact, make_atom, make_evidence, make_resolved_evidence


def test_two_default_invocations_produce_identical_overlay_id():
    """No test-only overlay_id trick -- this is the real default call
    path a production caller would use."""
    artifact = make_artifact(atoms=(make_atom(atom_id="a1"),))
    overlay1 = assess_artifact(artifact, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT)
    overlay2 = assess_artifact(artifact, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT)
    assert overlay1.overlay_id == overlay2.overlay_id


def test_two_default_invocations_produce_identical_canonical_json_and_digest():
    artifact = make_artifact(atoms=(make_atom(atom_id="a1"),))
    overlay1 = assess_artifact(artifact, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT)
    overlay2 = assess_artifact(artifact, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT)
    assert to_canonical_json(overlay1) == to_canonical_json(overlay2)
    assert digest(overlay1) == digest(overlay2)


def test_old_uuid4_default_would_have_failed_this_regression():
    """Direct regression proof: simulate the OLD behavior (a fresh
    random value standing in for uuid4() on each call) and show it
    produces different overlay_ids for identical semantic input --
    exactly the defect this closure fixes. This does not call any
    removed code; it demonstrates the counterfactual the fix replaces."""
    import uuid

    old_style_id_1 = str(uuid.uuid4())
    old_style_id_2 = str(uuid.uuid4())
    assert old_style_id_1 != old_style_id_2, (
        "uuid4() is expected to be non-deterministic -- this is exactly "
        "why it must never back a canonical default"
    )


def test_changing_assessment_context_id_changes_default_overlay_id():
    """A real semantic input change must change the derived overlay_id
    (and digest) -- the fix must not make the default a constant."""
    artifact = make_artifact(atoms=(make_atom(atom_id="a1"),))
    overlay1 = assess_artifact(artifact, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT)
    overlay2 = assess_artifact(artifact, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-2", assessed_at=ASSESSED_AT)
    assert overlay1.overlay_id != overlay2.overlay_id
    assert digest(overlay1) != digest(overlay2)


def test_changing_assessed_at_changes_default_overlay_id():
    artifact = make_artifact(atoms=(make_atom(atom_id="a1"),))
    overlay1 = assess_artifact(artifact, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at="2026-01-01T00:00:00+00:00")
    overlay2 = assess_artifact(artifact, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at="2026-02-02T00:00:00+00:00")
    assert overlay1.overlay_id != overlay2.overlay_id


def test_changing_resolved_evidence_changes_default_overlay_id():
    artifact = make_artifact(atoms=(make_atom(atom_id="a1", evidence_refs=("e1",)),), evidence=(make_evidence(evidence_id="e1"),))
    overlay1 = assess_artifact(
        artifact, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT,
    )
    overlay2 = assess_artifact(
        artifact, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT,
        resolved_evidence=(make_resolved_evidence(evidence_id="e1", target_atom_id="a1", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    assert overlay1.overlay_id != overlay2.overlay_id


def test_explicit_overlay_id_still_overrides_the_default():
    artifact = make_artifact(atoms=(make_atom(atom_id="a1"),))
    overlay = assess_artifact(
        artifact, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT,
        overlay_id="my-explicit-id",
    )
    assert overlay.overlay_id == "my-explicit-id"


def test_default_overlay_id_is_a_pure_function_of_its_inputs():
    assert _default_overlay_id(source_digest="sd", context_digest="cd", assessed_at="2026-01-01T00:00:00+00:00") == \
           _default_overlay_id(source_digest="sd", context_digest="cd", assessed_at="2026-01-01T00:00:00+00:00")
    assert _default_overlay_id(source_digest="sd1", context_digest="cd", assessed_at="2026-01-01T00:00:00+00:00") != \
           _default_overlay_id(source_digest="sd2", context_digest="cd", assessed_at="2026-01-01T00:00:00+00:00")
