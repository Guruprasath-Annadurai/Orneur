from __future__ import annotations

import pytest

from orneur.intelligence.ocl.enums import AtomKind, ProducerKind, TransformationOperation
from orneur.intelligence.ocl.errors import ConservationViolation
from orneur.intelligence.ocl.provenance import Provenance
from orneur.intelligence.ocl.transformations import TransformationRecord, validate_conservation
from tests.ocl.conftest import FIXED_TIME, make_artifact, make_atom


def _transform_producer():
    return Provenance(producer_kind=ProducerKind.TRANSFORMATION, producer_id="ocl.compiler")


def test_important_atom_silently_disappearing_is_a_conservation_violation():
    parent = make_artifact(artifact_id="p", atoms=(make_atom("h1", kind=AtomKind.HYPOTHESIS),))
    child = make_artifact(artifact_id="c", atoms=())
    record = TransformationRecord(
        transformation_id="t1", parent_artifact_id="p", child_artifact_id="c",
        producer=_transform_producer(), operation=TransformationOperation.REFINE,
        timestamp=FIXED_TIME, schema_version="1.0.0",
    )
    with pytest.raises(ConservationViolation):
        validate_conservation(parent, child, record)


def test_explicit_supersession_is_accepted():
    parent = make_artifact(artifact_id="p", atoms=(make_atom("h1", kind=AtomKind.HYPOTHESIS),))
    child = make_artifact(artifact_id="c", atoms=(make_atom("h2", kind=AtomKind.HYPOTHESIS),))
    record = TransformationRecord(
        transformation_id="t1", parent_artifact_id="p", child_artifact_id="c",
        producer=_transform_producer(), operation=TransformationOperation.SUPERSEDE,
        timestamp=FIXED_TIME, schema_version="1.0.0",
        superseded_atom_ids=("h1",), created_atom_ids=("h2",),
    )
    validate_conservation(parent, child, record)


def test_explicit_removal_with_reason_is_accepted():
    parent = make_artifact(artifact_id="p", atoms=(make_atom("h1", kind=AtomKind.ASSUMPTION),))
    child = make_artifact(artifact_id="c", atoms=())
    record = TransformationRecord(
        transformation_id="t1", parent_artifact_id="p", child_artifact_id="c",
        producer=_transform_producer(), operation=TransformationOperation.REMOVE_WITH_REASON,
        timestamp=FIXED_TIME, schema_version="1.0.0",
        removed_atom_ids=("h1",), justification_refs=("reason: assumption falsified by E9",),
    )
    validate_conservation(parent, child, record)


def test_same_id_semantic_rewrite_without_disposition_is_a_conservation_violation():
    """Phase 17 closure: a same-ID atom whose semantic content changed
    (parent 'the fix works' -> child 'the fix does NOT work', same
    atom_id) must not pass silently just because the ID is still present.
    Verified as a real, reproduced gap against commit ea9426f's
    transformations.py, which only checked ID presence."""
    parent = make_artifact(artifact_id="p", atoms=(make_atom("h1", kind=AtomKind.HYPOTHESIS, content="the fix works"),))
    child = make_artifact(artifact_id="c", atoms=(make_atom("h1", kind=AtomKind.HYPOTHESIS, content="the fix does NOT work"),))
    record = TransformationRecord(
        transformation_id="t1", parent_artifact_id="p", child_artifact_id="c",
        producer=_transform_producer(), operation=TransformationOperation.REFINE,
        timestamp=FIXED_TIME, schema_version="1.0.0",
    )
    with pytest.raises(ConservationViolation):
        validate_conservation(parent, child, record)


def test_same_id_semantic_rewrite_with_modified_disposition_is_accepted():
    from orneur.intelligence.ocl.transformations import AtomDisposition

    parent = make_artifact(artifact_id="p", atoms=(make_atom("h1", kind=AtomKind.HYPOTHESIS, content="the fix works"),))
    child = make_artifact(artifact_id="c", atoms=(make_atom("h1", kind=AtomKind.HYPOTHESIS, content="the fix does NOT work"),))
    record = TransformationRecord(
        transformation_id="t1", parent_artifact_id="p", child_artifact_id="c",
        producer=_transform_producer(), operation=TransformationOperation.REFINE,
        timestamp=FIXED_TIME, schema_version="1.0.0",
        atom_dispositions=(AtomDisposition(atom_id="h1", disposition="MODIFIED", justification_ref="evidence: E9 falsified original hypothesis"),),
    )
    validate_conservation(parent, child, record)


def test_atom_disposition_requires_non_empty_justification():
    from orneur.intelligence.ocl.transformations import AtomDisposition

    with pytest.raises(ConservationViolation):
        AtomDisposition(atom_id="h1", disposition="MODIFIED", justification_ref="")


def test_atom_disposition_rejects_unknown_disposition_value():
    from orneur.intelligence.ocl.transformations import AtomDisposition

    with pytest.raises(ConservationViolation):
        AtomDisposition(atom_id="h1", disposition="WHATEVER", justification_ref="x")


def test_unchanged_same_id_atom_requires_no_disposition():
    parent = make_artifact(artifact_id="p", atoms=(make_atom("h1", kind=AtomKind.HYPOTHESIS, content="stable"),))
    child = make_artifact(artifact_id="c", atoms=(make_atom("h1", kind=AtomKind.HYPOTHESIS, content="stable"),))
    record = TransformationRecord(
        transformation_id="t1", parent_artifact_id="p", child_artifact_id="c",
        producer=_transform_producer(), operation=TransformationOperation.REFINE,
        timestamp=FIXED_TIME, schema_version="1.0.0",
    )
    validate_conservation(parent, child, record)


def test_non_important_atom_kind_may_disappear_without_a_record():
    """QUESTION is scaffolding, not a tracked-important kind in the
    documented V1 definition -- churn here is expected."""
    parent = make_artifact(artifact_id="p", atoms=(make_atom("q1", kind=AtomKind.QUESTION),))
    child = make_artifact(artifact_id="c", atoms=())
    record = TransformationRecord(
        transformation_id="t1", parent_artifact_id="p", child_artifact_id="c",
        producer=_transform_producer(), operation=TransformationOperation.REFINE,
        timestamp=FIXED_TIME, schema_version="1.0.0",
    )
    validate_conservation(parent, child, record)
