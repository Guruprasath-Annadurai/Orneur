"""
Phase 17 type-parity closure section 9: TransformationRecord/
AtomDisposition type safety only -- no expansion of Cognitive Conservation
semantics. `operation` must be a genuine TransformationOperation,
`producer` a genuine Provenance, and every tuple/list ID field must
contain only strings.
"""
from __future__ import annotations

import pytest

from orneur.intelligence.ocl.enums import ProducerKind, TransformationOperation
from orneur.intelligence.ocl.errors import ConservationViolation
from orneur.intelligence.ocl.provenance import Provenance
from orneur.intelligence.ocl.transformations import AtomDisposition, TransformationRecord

FIXED_TIME = "2026-01-01T00:00:00+00:00"


def _valid_producer():
    return Provenance(producer_kind=ProducerKind.TRANSFORMATION, producer_id="ocl.compiler")


def _base_kwargs(**overrides):
    kwargs = dict(
        transformation_id="t1", parent_artifact_id="p", child_artifact_id="c",
        producer=_valid_producer(), operation=TransformationOperation.REFINE,
        timestamp=FIXED_TIME, schema_version="1.0.0",
    )
    kwargs.update(overrides)
    return kwargs


def test_valid_transformation_record_still_constructs():
    TransformationRecord(**_base_kwargs())


def test_operation_wrong_type_rejected():
    with pytest.raises(ConservationViolation):
        TransformationRecord(**_base_kwargs(operation="REFINE"))


def test_producer_wrong_type_rejected():
    with pytest.raises(ConservationViolation):
        TransformationRecord(**_base_kwargs(producer={"producer_kind": "TRANSFORMATION"}))


@pytest.mark.parametrize("field", ["affected_atom_ids", "created_atom_ids", "superseded_atom_ids", "removed_atom_ids"])
def test_id_sequence_field_wrong_element_type_rejected(field):
    with pytest.raises(ConservationViolation):
        TransformationRecord(**_base_kwargs(**{field: (42,)}))


def test_justification_refs_wrong_element_type_rejected():
    with pytest.raises(ConservationViolation):
        TransformationRecord(**_base_kwargs(justification_refs=(42,)))


def test_justification_refs_allows_empty_string_element():
    """Type safety only, not a semantics change: the existing
    'shared justification' lookup already filters falsy entries itself."""
    TransformationRecord(**_base_kwargs(justification_refs=("", "real justification")))


def test_atom_dispositions_wrong_element_type_rejected():
    with pytest.raises(ConservationViolation):
        TransformationRecord(**_base_kwargs(atom_dispositions=({"atom_id": "a1"},)))


def test_atom_dispositions_genuine_element_still_constructs():
    disp = AtomDisposition(atom_id="a1", disposition="REMOVED", justification_ref="because")
    TransformationRecord(**_base_kwargs(atom_dispositions=(disp,)))


def test_atom_disposition_atom_id_wrong_type_rejected():
    with pytest.raises(ConservationViolation):
        AtomDisposition(atom_id=42, disposition="REMOVED", justification_ref="because")


def test_atom_disposition_atom_id_empty_string_rejected():
    with pytest.raises(ConservationViolation):
        AtomDisposition(atom_id="", disposition="REMOVED", justification_ref="because")
