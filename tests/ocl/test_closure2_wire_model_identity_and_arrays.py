"""
Phase 17 acceptance-boundary closure section 4: the strict JSON parser
must validate EVERY model_identity field, and every string-array
element's type, not merely the outer array shape.
"""
from __future__ import annotations

import json

import pytest

from orneur.intelligence.ocl.canonical import compile_ocl_json, parse_ocl_draft_json
from orneur.intelligence.ocl.errors import MalformedWireShape, OclError


def _base_payload(**overrides) -> dict:
    payload = {
        "artifact_id": "art-1", "schema_version": "1.0.0", "request_id": "req-1",
        "created_at": "2026-01-01T00:00:00+00:00",
        "provenance": {"producer_kind": "NATIVE_MODEL", "producer_id": "x", "model_identity": {"family": "genesis"}},
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize("bad_family", [[], {}, 42])
def test_wire_model_identity_family_wrong_type_raises_typed_error(bad_family):
    payload = _base_payload(provenance={"producer_kind": "NATIVE_MODEL", "producer_id": "x", "model_identity": {"family": bad_family}})
    with pytest.raises(OclError):
        compile_ocl_json(json.dumps(payload))


@pytest.mark.parametrize("bad_lifecycle", [[], {}, 42])
def test_wire_model_identity_lifecycle_state_wrong_type_raises_typed_error(bad_lifecycle):
    payload = _base_payload(provenance={"producer_kind": "NATIVE_MODEL", "producer_id": "x", "model_identity": {"family": "genesis", "lifecycle_state": bad_lifecycle}})
    with pytest.raises(OclError):
        compile_ocl_json(json.dumps(payload))


@pytest.mark.parametrize("bad_generation", [[], {}, "not-an-int", 1.5])
def test_wire_model_identity_generation_wrong_type_raises_typed_error(bad_generation):
    payload = _base_payload(provenance={"producer_kind": "NATIVE_MODEL", "producer_id": "x", "model_identity": {"family": "genesis", "generation": bad_generation}})
    with pytest.raises(OclError):
        compile_ocl_json(json.dumps(payload))


@pytest.mark.parametrize("field,bad_array", [
    ("preconditions", [42]),
    ("risk_hints", [None]),
    ("verification_requirement_refs", [True]),
])
def test_action_intent_string_array_element_type_enforced_on_wire(field, bad_array):
    payload = _base_payload(action_intents=[{"intent_id": "i1", "proposed_capability": "x", field: bad_array}])
    with pytest.raises(OclError):
        compile_ocl_json(json.dumps(payload))


def test_evidence_refs_element_wrong_type_on_wire():
    payload = _base_payload(atoms=[{
        "atom_id": "a1", "kind": "ASSERTION", "source_class": "MODEL_ASSERTION", "content": "x",
        "evidence_refs": [{}],
    }])
    with pytest.raises(OclError):
        compile_ocl_json(json.dumps(payload))


def test_pass_conditions_element_wrong_type_on_wire():
    payload = _base_payload(
        atoms=[{"atom_id": "a1", "kind": "ASSERTION", "source_class": "MODEL_ASSERTION", "content": "x"}],
        verification_contracts=[{"contract_id": "v1", "target_atom_ref": "a1", "pass_conditions": [True]}],
    )
    with pytest.raises(OclError):
        compile_ocl_json(json.dumps(payload))


def test_reason_categories_element_wrong_type_on_wire():
    payload = _base_payload(escalation_requests=[{"escalation_id": "e1", "reason_categories": [42]}])
    with pytest.raises(OclError):
        compile_ocl_json(json.dumps(payload))


def test_valid_model_identity_still_compiles():
    payload = _base_payload()
    compile_ocl_json(json.dumps(payload))
