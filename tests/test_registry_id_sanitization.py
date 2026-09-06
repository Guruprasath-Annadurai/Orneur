"""
Registry IDs (checkpoint_id, dataset_id, run_id, evaluation_id) are used to
build file paths under ORCA_HOME/registry/. An unsanitized ID is a
path-traversal vector -- the same bug class fixed in orca/mcp/fs_server.py
earlier this phase. These tests confirm every registry manifest type
rejects a traversal attempt rather than silently writing/reading outside
its registry directory.
"""
from __future__ import annotations

import pytest

from orca.registry._ids import InvalidRegistryId, validate_id
from orca.registry.checkpoint import CheckpointRecord
from orca.registry.dataset_manifest import DatasetManifest
from orca.registry.evaluation_registry import EvaluationReport
from orca.registry.training_run import TrainingRunManifest

TRAVERSAL_IDS = ["../../etc/passwd", "..", "/etc/passwd", "a/../../b", "a/b"]


@pytest.mark.parametrize("bad_id", TRAVERSAL_IDS)
def test_validate_id_rejects_traversal(bad_id):
    with pytest.raises(InvalidRegistryId):
        validate_id(bad_id)


def test_validate_id_accepts_normal_ids():
    for ok in ["orca-core-combined-v2", "orneur-novus", "run_2026-08-29.1"]:
        assert validate_id(ok) == ok


@pytest.mark.parametrize("bad_id", TRAVERSAL_IDS)
def test_checkpoint_manifest_path_rejects_traversal(bad_id):
    rec = CheckpointRecord(
        checkpoint_id=bad_id, model_id="orneur-novus", run_id="r", step_or_epoch="e",
        base_model="x", dataset_manifest_ids=[], training_config_summary="x",
        optimizer_state_available=False, scheduler_state_available=False,
        tokenizer_identity="x", artifact_path="na", artifact_checksum="na",
    )
    with pytest.raises(InvalidRegistryId):
        rec.manifest_path()


@pytest.mark.parametrize("bad_id", TRAVERSAL_IDS)
def test_dataset_manifest_path_rejects_traversal(bad_id):
    m = DatasetManifest(
        dataset_id=bad_id, version="v1", purpose="x", source_paths=[],
        record_count=0, schema="x", train_checksum="x", eval_checksum="x",
        creation_code_sha="x", filters_applied="x", deduplication_result="x",
    )
    with pytest.raises(InvalidRegistryId):
        m.manifest_path()


@pytest.mark.parametrize("bad_id", TRAVERSAL_IDS)
def test_training_run_manifest_path_rejects_traversal(bad_id):
    run = TrainingRunManifest(
        run_id=bad_id, model_id="orneur-novus", base_model="x",
        dataset_manifest_ids=[], training_config={}, hyperparameters={},
        seed=None, precision="fp16", hardware_info="x",
    )
    with pytest.raises(InvalidRegistryId):
        run.manifest_path()


@pytest.mark.parametrize("bad_id", TRAVERSAL_IDS)
def test_evaluation_report_path_rejects_traversal(bad_id):
    report = EvaluationReport(
        evaluation_id=bad_id, checkpoint_id="x", family="novus",
        evaluator_version="x", dataset_version="x", metrics={},
        acceptance_thresholds={},
    )
    with pytest.raises(InvalidRegistryId):
        report.manifest_path()
