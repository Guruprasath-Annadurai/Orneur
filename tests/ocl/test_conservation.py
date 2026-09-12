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
