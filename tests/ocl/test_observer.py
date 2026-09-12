from __future__ import annotations

from orneur.intelligence.ocl.compiler import compile_artifact
from orneur.intelligence.ocl.enums import AtomKind, ObserverView
from orneur.intelligence.ocl.observer import project
from tests.ocl.conftest import make_artifact, make_atom


def test_human_summary_view_contains_only_intended_fields():
    artifact = compile_artifact(make_artifact(atoms=(
        make_atom("a1", kind=AtomKind.ASSERTION, content="claim"),
        make_atom("a2", kind=AtomKind.LIMITATION, content="limit"),
    ), limitation_atom_refs=("a2",)))
    view = project(artifact, ObserverView.HUMAN_SUMMARY_VIEW)
    assert set(view.keys()) == {"artifact_id", "claims", "unknowns", "proposed_next_steps", "limitations", "evidence_ids"}
    assert len(view["claims"]) == 1
    assert len(view["limitations"]) == 1


def test_projection_never_mutates_source_artifact():
    artifact = compile_artifact(make_artifact(atoms=(make_atom("a1"),)))
    before = artifact
    project(artifact, ObserverView.AUDIT_VIEW)["atoms"][0]["content"] = "TAMPERED"
    assert artifact == before
    assert artifact.atoms[0].content != "TAMPERED"


def test_all_views_are_deterministic():
    artifact = compile_artifact(make_artifact(atoms=(make_atom("a1"), make_atom("a2"))))
    for view in ObserverView:
        assert project(artifact, view) == project(artifact, view)


def test_audit_view_contains_full_artifact():
    artifact = compile_artifact(make_artifact(atoms=(make_atom("a1"),)))
    view = project(artifact, ObserverView.AUDIT_VIEW)
    assert view["artifact_id"] == artifact.artifact_id
    assert len(view["atoms"]) == 1
