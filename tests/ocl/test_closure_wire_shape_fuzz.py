"""
Phase 17 final closure section 8: no raw AttributeError/TypeError/
KeyError/ValueError may escape `parse_ocl_draft_json`/`compile_ocl_json`
-- every malformed nested shape becomes a typed `MalformedWireShape`.
"""
from __future__ import annotations

import json

import pytest

from orneur.intelligence.ocl.canonical import parse_ocl_draft_json
from orneur.intelligence.ocl.errors import MalformedWireShape, MissingMandatoryField, OclError


def _base_payload(**overrides) -> dict:
    payload = {
        "artifact_id": "art-1",
        "schema_version": "1.0.0",
        "request_id": "req-1",
        "created_at": "2026-01-01T00:00:00+00:00",
        "provenance": {"producer_kind": "NATIVE_MODEL", "producer_id": "x",
                       "model_identity": {"family": "genesis"}},
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize("bad_provenance", [[], "fake", 42, None])
def test_malformed_provenance_shape_raises_typed_error(bad_provenance):
    payload = _base_payload(provenance=bad_provenance)
    with pytest.raises(OclError):
        parse_ocl_draft_json(json.dumps(payload))


@pytest.mark.parametrize("bad_atoms", [[42], ["not-an-object"], "not-an-array", {"not": "array"}])
def test_malformed_atoms_shape_raises_typed_error(bad_atoms):
    payload = _base_payload(atoms=bad_atoms)
    with pytest.raises(OclError):
        parse_ocl_draft_json(json.dumps(payload))


def test_evidence_array_with_null_entry_raises_typed_error():
    payload = _base_payload(evidence=[None])
    with pytest.raises(MalformedWireShape):
        parse_ocl_draft_json(json.dumps(payload))


def test_action_intents_with_malformed_field_type_raises_typed_error():
    payload = _base_payload(action_intents=[{"intent_id": 42, "proposed_capability": "x"}])
    with pytest.raises(MalformedWireShape):
        parse_ocl_draft_json(json.dumps(payload))


def test_action_intents_missing_required_field_raises_typed_error():
    payload = _base_payload(action_intents=[{"intent_id": "i1"}])  # missing proposed_capability
    with pytest.raises(MissingMandatoryField):
        parse_ocl_draft_json(json.dumps(payload))


@pytest.mark.parametrize("bad_identity", [[], "fake", 42])
def test_malformed_model_identity_shape_raises_typed_error(bad_identity):
    payload = _base_payload(provenance={"producer_kind": "NATIVE_MODEL", "producer_id": "x", "model_identity": bad_identity})
    with pytest.raises(OclError):
        parse_ocl_draft_json(json.dumps(payload))


@pytest.mark.parametrize("bad_metadata", ["not-an-object", 42, []])
def test_malformed_metadata_shape_raises_typed_error(bad_metadata):
    payload = _base_payload(metadata=bad_metadata)
    with pytest.raises(MalformedWireShape):
        parse_ocl_draft_json(json.dumps(payload))


@pytest.mark.parametrize("field", ["relations", "evidence", "action_intents", "verification_contracts", "escalation_requests", "causal_hypotheses", "counterfactual_branches", "limitation_atom_refs"])
def test_every_top_level_collection_rejects_a_non_array_value(field):
    payload = _base_payload(**{field: "not-an-array"})
    with pytest.raises(MalformedWireShape):
        parse_ocl_draft_json(json.dumps(payload))


def test_no_raw_python_exception_types_ever_escape():
    """Blanket assertion across every malformed case above: the raised
    exception is always an OclError subclass, never a bare AttributeError/
    TypeError/KeyError/ValueError."""
    cases = [
        _base_payload(provenance=[]),
        _base_payload(atoms=[42]),
        _base_payload(evidence=[None]),
        _base_payload(metadata="not-an-object"),
    ]
    for payload in cases:
        try:
            parse_ocl_draft_json(json.dumps(payload))
        except OclError:
            pass
        except (AttributeError, TypeError, KeyError, ValueError) as exc:
            pytest.fail(f"raw Python exception {type(exc).__name__} escaped for payload {payload!r}: {exc}")
