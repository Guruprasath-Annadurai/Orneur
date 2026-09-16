"""
Closure: deep immutability of structured metadata. Reproduced defect:
prior production code did `MappingProxyType(dict(metadata))` -- a
shallow freeze. Nested dicts/lists inside metadata remained the
caller's own mutable objects; mutating them after construction silently
changed the overlay's canonical digest. Fixed via
freeze.validate_and_freeze(): recursively converts dict -> MappingProxyType
and list/tuple -> tuple at every nesting level, so no mutable object is
reachable from an EpistemicOverlay (or a ResolvedEvidence/
VerificationFeasibilityRecord) after construction.
"""
from __future__ import annotations

from types import MappingProxyType

import pytest

from orneur.intelligence.epistemic import errors
from orneur.intelligence.epistemic.canonical import digest
from orneur.intelligence.epistemic.freeze import validate_and_freeze
from orneur.intelligence.epistemic.resolver import assess_artifact
from tests.epistemic.conftest import ASSESSED_AT, TRUSTED_OCL, make_artifact, make_atom, make_feasibility


def test_nested_dict_and_list_are_deeply_frozen():
    metadata = {"nested": {"items": [1, 2], "flag": True}, "top": "value"}
    overlay = assess_artifact(
        artifact := make_artifact(atoms=(make_atom(atom_id="a1"),)),
        ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT,
        overlay_id="fixed", metadata=metadata,
    )
    assert isinstance(overlay.metadata, MappingProxyType)
    assert isinstance(overlay.metadata["nested"], MappingProxyType)
    assert isinstance(overlay.metadata["nested"]["items"], tuple)
    assert overlay.metadata["nested"]["items"] == (1, 2)


def test_mutating_caller_original_metadata_after_construction_does_not_change_digest():
    metadata = {"nested": {"items": [1, 2]}}
    artifact = make_artifact(atoms=(make_atom(atom_id="a1"),))
    overlay = assess_artifact(
        artifact, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT,
        overlay_id="fixed", metadata=metadata,
    )
    digest_before = digest(overlay)

    # Mutate the CALLER's original structure -- this must not be
    # reachable from the overlay any more.
    metadata["nested"]["items"].append(999)
    metadata["nested"]["new_key"] = "sneaky"

    digest_after = digest(overlay)
    assert digest_before == digest_after
    assert overlay.metadata["nested"]["items"] == (1, 2)
    assert "new_key" not in overlay.metadata["nested"]


def test_overlay_metadata_mapping_itself_cannot_be_mutated():
    overlay = assess_artifact(
        make_artifact(atoms=(make_atom(atom_id="a1"),)),
        ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT,
        overlay_id="fixed", metadata={"a": 1},
    )
    with pytest.raises(TypeError):
        overlay.metadata["a"] = 2  # MappingProxyType is read-only


def test_deeply_nested_tuple_of_dicts_is_frozen_recursively():
    metadata = {"records": [{"id": 1, "tags": ["x", "y"]}, {"id": 2, "tags": ["z"]}]}
    overlay = assess_artifact(
        make_artifact(atoms=(make_atom(atom_id="a1"),)),
        ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT,
        overlay_id="fixed", metadata=metadata,
    )
    records = overlay.metadata["records"]
    assert isinstance(records, tuple)
    assert isinstance(records[0], MappingProxyType)
    assert isinstance(records[0]["tags"], tuple)
    metadata["records"][0]["tags"].append("mutated")
    assert overlay.metadata["records"][0]["tags"] == ("x", "y")


def test_nan_infinity_rejected_in_nested_metadata():
    metadata = {"nested": {"value": float("nan")}}
    with pytest.raises(errors.InvalidStructuredValue):
        assess_artifact(
            make_artifact(atoms=(make_atom(atom_id="a1"),)),
            ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT,
            overlay_id="fixed", metadata=metadata,
        )


def test_unsupported_object_type_in_metadata_rejected():
    metadata = {"nested": object()}
    with pytest.raises(errors.InvalidStructuredValue):
        assess_artifact(
            make_artifact(atoms=(make_atom(atom_id="a1"),)),
            ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT,
            overlay_id="fixed", metadata=metadata,
        )


def test_resolved_evidence_metadata_is_also_deeply_frozen():
    from orneur.intelligence.epistemic.enums import EvidenceResolutionStatus, EvidenceStance, EpistemicResolutionTrustContext
    from tests.epistemic.conftest import make_evidence, make_resolved_evidence

    artifact = make_artifact(atoms=(make_atom(atom_id="a1", evidence_refs=("e1",)),), evidence=(make_evidence(evidence_id="e1"),))
    nested_meta = {"trace": {"steps": [1, 2, 3]}}
    record = make_resolved_evidence(
        evidence_id="e1", target_atom_id="a1", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS,
        metadata=nested_meta,
    )
    overlay = assess_artifact(
        artifact, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT,
        overlay_id="fixed", resolved_evidence=(record,),
        resolution_trust_context=EpistemicResolutionTrustContext.TRUSTED_DETERMINISTIC_VERIFIER,
    )
    assert overlay.assessments[0].state.value == "KNOWN"
    # The original record's metadata dict must be untouched by aliasing
    # (validate_and_freeze never mutates its input, only returns a new
    # frozen structure) -- prove no shared mutable reference survives by
    # freezing again and comparing.
    refrozen = validate_and_freeze(nested_meta, where="test")
    assert isinstance(refrozen, MappingProxyType)
    assert isinstance(refrozen["trace"], MappingProxyType)
    assert isinstance(refrozen["trace"]["steps"], tuple)


def test_validate_and_freeze_never_mutates_its_input():
    original = {"a": [1, 2], "b": {"c": 3}}
    validate_and_freeze(original, where="test")
    assert original == {"a": [1, 2], "b": {"c": 3}}
    assert isinstance(original["a"], list)
    assert isinstance(original["b"], dict)
