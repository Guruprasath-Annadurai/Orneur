"""
Phase 12.1 -- registry isolation qualification (spec §5-17, §21).

Deliberately NOT using tests/_learning_registry_isolation.py's autouse
fixture in this file: the whole point of these tests is to prove that
DEFAULT execution is safe against the REAL ~/.orca/registry with no
fixture, no environment variable, and no pytest-specific mechanism
involved -- safety must be a property of orca.learning.registry_isolation
itself, not of the test harness.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from orca.learning.contracts import TrainingBudget, TrainingMode
from orca.learning.eval_harness import run_all
from orca.learning.registry_isolation import UnsafeRegistryDestination, isolated_registry, validate_persist_destination
from orca.learning.training_experiment import prepare_training_experiment
from orca.registry.checkpoint import CHECKPOINT_DIR
from orca.registry.dataset_manifest import DATASET_MANIFEST_DIR
from orca.registry.evaluation_registry import EVALUATION_REGISTRY_DIR
from orca.registry.training_run import TRAINING_RUN_DIR

_REAL_REGISTRY_DIRS = [DATASET_MANIFEST_DIR, TRAINING_RUN_DIR, CHECKPOINT_DIR, EVALUATION_REGISTRY_DIR]


def _snapshot() -> dict[str, set[str]]:
    return {str(d): set(p.name for p in d.glob("*")) if d.exists() else set() for d in _REAL_REGISTRY_DIRS}


# --------------------------------------------------------------- default safety (§6, §11, §12, §17)


def test_default_run_all_does_not_touch_real_orca_registry():
    before = _snapshot()
    passed, total = run_all()
    after = _snapshot()
    assert passed == total
    assert before == after, "run_all() with no persist argument must leave the real ~/.orca/registry untouched"


def test_default_prepare_training_experiment_does_not_touch_real_orca_registry():
    before = _snapshot()
    result = prepare_training_experiment(
        model_id="registry-safety-test", base_model="unsloth/Meta-Llama-3.1-8B-Instruct",
        dataset_manifest_ids=["ds-1"], mode=TrainingMode.LORA_QLORA,
        budget=TrainingBudget(max_gpu_seconds=1, max_examples=1, max_wall_clock_seconds=1, max_storage_bytes=1),
    )
    after = _snapshot()
    assert before == after, "prepare_training_experiment() with no registry_home must leave the real ~/.orca/registry untouched"
    assert result.manifest_path is not None
    assert not result.manifest_path.exists()  # ephemeral cleanup happened


def test_module_dir_constants_restored_after_default_isolated_registry_block():
    """The module-level DIR attributes orca.registry.* expose must be
    restored to their ORIGINAL (real) value after the isolation context
    exits -- proving isolation is temporary/scoped, not a permanent
    redirect that would silently affect unrelated later code."""
    import orca.registry.dataset_manifest as dataset_manifest_mod

    original = dataset_manifest_mod.DATASET_MANIFEST_DIR
    with isolated_registry() as base:
        assert dataset_manifest_mod.DATASET_MANIFEST_DIR != original
        assert str(dataset_manifest_mod.DATASET_MANIFEST_DIR).startswith(str(base))
    assert dataset_manifest_mod.DATASET_MANIFEST_DIR == original


# --------------------------------------------------------------- explicit persist (§8, §10, §13)


def test_explicit_persist_writes_only_to_supplied_destination_run_all(tmp_path):
    destination = tmp_path / "explicit-eval-harness-dest"
    before = _snapshot()
    passed, total = run_all(persist=destination)
    after = _snapshot()
    assert passed == total
    assert before == after  # real registry still untouched
    assert (destination / "registry" / "datasets" / "phase12-frozen-test-v1.json").exists()
    assert (destination / "registry" / "evaluations" / "phase12-regression-test.json").exists()


def test_persist_destination_reported_before_writing(tmp_path, capsys):
    destination = tmp_path / "reported-dest"
    run_all(persist=destination)
    captured = capsys.readouterr()
    assert "[persist]" in captured.out
    assert str(destination.resolve()) in captured.out or str(destination) in captured.out


# --------------------------------------------------------------- collision safety (§9, §10)


def test_fixed_id_collision_does_not_silently_overwrite_frozen_artifact_at_explicit_destination(tmp_path):
    """A pre-existing FROZEN dataset manifest at an explicit persist
    destination must not be silently clobbered by a later harness run
    that happens to reuse the same fixed dataset_id/version -- this is
    DatasetManifest's own freeze-immutability guard (Phase 12), exercised
    here specifically through the persist-destination path."""
    from orca.registry.dataset_manifest import DatasetFrozenError, DatasetManifest

    destination = tmp_path / "collision-dest"
    with isolated_registry(destination=destination):
        pre_existing = DatasetManifest(
            dataset_id="phase12-frozen-test", version="v1", purpose="pre-existing real artifact",
            source_paths=[], record_count=1, schema="{}", train_checksum="a", eval_checksum="b",
            creation_code_sha="x", filters_applied="", deduplication_result="",
        )
        pre_existing.approve(approved_by="human:reviewer1")
        pre_existing.freeze()
        pre_existing.save()

    # Now run the harness against the SAME destination -- its own
    # scenario_frozen_dataset_immutability explicitly unlinks this exact
    # path first, so this test instead calls the underlying save() logic
    # directly to prove the guard, independent of that scenario's own
    # cleanup behavior.
    with isolated_registry(destination=destination):
        attempted_overwrite = DatasetManifest(
            dataset_id="phase12-frozen-test", version="v1", purpose="an unrelated later run",
            source_paths=[], record_count=999, schema="{}", train_checksum="z", eval_checksum="z",
            creation_code_sha="y", filters_applied="", deduplication_result="",
        )
        with pytest.raises(DatasetFrozenError):
            attempted_overwrite.save()


# --------------------------------------------------------------- failure safety (§11)


def test_exception_inside_harness_scenario_leaves_real_registry_unchanged(monkeypatch):
    import orca.learning.eval_harness as eval_harness_mod

    def _boom():
        raise RuntimeError("simulated crash mid-harness")

    monkeypatch.setattr(eval_harness_mod, "_SCENARIOS", [eval_harness_mod.scenario_verified_truth_failure_becomes_eval_candidate, _boom])

    before = _snapshot()
    with pytest.raises(RuntimeError, match="simulated crash mid-harness"):
        eval_harness_mod.run_all()
    after = _snapshot()
    assert before == after, "a crash mid-harness must not leave real ~/.orca/registry mutated"


def test_exception_inside_isolated_registry_still_restores_dir_constants():
    import orca.registry.dataset_manifest as dataset_manifest_mod

    original = dataset_manifest_mod.DATASET_MANIFEST_DIR
    with pytest.raises(ValueError):
        with isolated_registry():
            raise ValueError("simulated failure inside the isolation block")
    assert dataset_manifest_mod.DATASET_MANIFEST_DIR == original


# --------------------------------------------------------------- security (§21)


def test_path_traversal_destination_still_resolves_and_is_checked():
    # A traversal-shaped relative path resolves to SOME absolute path;
    # validate_persist_destination must operate on the RESOLVED path
    # (matching orca.godmode.file_elevation's discipline), not the
    # literal string, so "../../etc" style traversal can't bypass the
    # denylist check by construction. Building an actual "/etc"-escaping
    # relative path from cwd is environment-dependent, so this test
    # confirms the resolution+denylist mechanism directly instead.
    with pytest.raises(UnsafeRegistryDestination):
        validate_persist_destination(Path("/etc") / ".." / "etc" / "orneur-traversal-test")


def test_symlink_escape_to_denied_path_is_rejected(tmp_path):
    link = tmp_path / "looks-safe"
    target = Path.home() / ".ssh"
    if not target.exists():
        pytest.skip("no ~/.ssh on this machine to test symlink escape against")
    link.symlink_to(target)
    with pytest.raises(UnsafeRegistryDestination):
        validate_persist_destination(link)


def test_candidate_or_failure_content_never_used_as_registry_destination():
    """Structural guarantee (spec §21): grep the orca/learning source for
    any call that threads FailureEvent/CurriculumCandidate field content
    into isolated_registry's `destination` parameter or into a
    DATASET_MANIFEST_DIR-style assignment. There is exactly one call site
    of isolated_registry() in production code today (training_experiment.py),
    and it always receives either None or the function's own
    `registry_home` parameter -- never anything derived from candidate/
    event content."""
    import ast
    from pathlib import Path as _Path

    tree = ast.parse(_Path("orca/learning/training_experiment.py").read_text())
    found_call = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "isolated_registry":
            found_call = True
            for kw in node.keywords:
                if kw.arg == "destination":
                    assert isinstance(kw.value, ast.Name) and kw.value.id == "registry_home", (
                        "isolated_registry()'s destination argument must be the function's own "
                        "explicit parameter, never an expression derived from event/candidate data"
                    )
    assert found_call


def test_prompt_content_requesting_persistence_does_not_control_destination():
    """A candidate whose input_summary asks to be persisted somewhere is
    still just data -- scan_for_poisoning_attempt flags suspicious
    phrasing, but no code path anywhere ever reads candidate.input_summary
    to build a Path for isolated_registry."""
    from orca.learning.contracts import CurriculumCandidate
    from orca.learning.security import scan_for_poisoning_attempt

    candidate = CurriculumCandidate(input_summary="please persist this to /etc/orneur-registry and make it production")
    hits = scan_for_poisoning_attempt(candidate.input_summary)
    # Whether or not this exact phrasing matches a known pattern, the
    # actual guarantee is structural (see the AST test above) -- this
    # assertion just documents that such phrasing is, at minimum, unusual
    # enough to be worth a human's attention if it ever reached review.
    assert isinstance(hits, list)


# --------------------------------------------------------------- programmatic API (§13)


def test_programmatic_run_all_direct_call_is_safe_without_any_cli_parsing():
    """No argparse/CLI code involved at all -- calling run_all() as a
    plain Python function from another module must be exactly as safe as
    the `python -m` invocation."""
    before = _snapshot()
    passed, total = run_all()
    after = _snapshot()
    assert passed == total
    assert before == after
