from __future__ import annotations

import pytest

from orca.learning.contracts import TrainingBudget, TrainingCostReport, TrainingExperimentStatus, TrainingFailureCategory, TrainingMode
from orca.learning.training_experiment import audit_hardware, cancel_training, prepare_training_experiment
from orca.registry.training_run import TrainingRunManifest


@pytest.fixture(autouse=True)
def _isolate_learning_registry_dirs(tmp_path, monkeypatch):
    """File-scoped registry isolation -- see test_learning_phase12.py's
    fixture of the same name for why this is not in tests/conftest.py.
    This is a SECOND, independent layer on top of
    orca.learning.registry_isolation's own default ephemeral isolation
    (which prepare_training_experiment now applies to itself) -- kept so
    `cancel_training()`'s direct TrainingRunManifest.save() call (which
    does not go through registry_isolation itself) is still covered."""
    from tests._learning_registry_isolation import isolate_registry_dirs
    isolate_registry_dirs(tmp_path, monkeypatch)


def test_audit_hardware_reports_real_environment_state():
    hw = audit_hardware()
    # This machine (Apple Silicon MacBook Air) genuinely has no CUDA device
    # and no unsloth/bitsandbytes installed -- asserting the real, observed
    # state rather than a mocked one.
    assert hw.cuda_available is False
    assert hw.can_run_qlora() is False


def test_prepare_training_experiment_default_is_ephemeral_and_leaves_no_trace():
    """Phase 12.1: default (no registry_home) must not persist anything
    a caller can find afterward -- the manifest is genuinely built and
    saved (proving TRAINING_READY validity) inside an ephemeral temp dir
    that is cleaned up before this function returns."""
    result = prepare_training_experiment(
        model_id="test-model", base_model="unsloth/Meta-Llama-3.1-8B-Instruct",
        dataset_manifest_ids=["ds-1"], mode=TrainingMode.LORA_QLORA,
        budget=TrainingBudget(max_gpu_seconds=100, max_examples=10, max_wall_clock_seconds=100, max_storage_bytes=1000),
    )
    assert result.status == TrainingExperimentStatus.TRAINING_READY
    assert "TRAINING_READY" in result.reason or "no training executed" in result.reason
    assert result.training_run_manifest is not None
    assert result.training_run_manifest.checkpoint_outputs == []  # no checkpoint fabricated
    assert result.manifest_path is not None
    assert not result.manifest_path.exists()  # ephemeral dir was cleaned up on return


def test_prepare_training_experiment_explicit_persist_writes_to_supplied_destination(tmp_path):
    destination = tmp_path / "explicit-registry-home"
    result = prepare_training_experiment(
        model_id="test-model-persisted", base_model="unsloth/Meta-Llama-3.1-8B-Instruct",
        dataset_manifest_ids=["ds-1"], mode=TrainingMode.LORA_QLORA,
        budget=TrainingBudget(max_gpu_seconds=100, max_examples=10, max_wall_clock_seconds=100, max_storage_bytes=1000),
        registry_home=destination,
    )
    assert result.manifest_path is not None
    assert result.manifest_path.exists()
    assert str(result.manifest_path).startswith(str(destination.resolve()))


def test_cancel_training_marks_cancelled_and_no_promotion():
    manifest = TrainingRunManifest(
        run_id="cancel-test-run", model_id="test-model", base_model="x", dataset_manifest_ids=[],
        training_config={}, hyperparameters={}, seed=1, precision="bf16", hardware_info="test",
    )
    manifest.save()

    result = cancel_training(manifest, partial_checkpoint_id="partial-ckpt-1")
    assert result.status == TrainingExperimentStatus.CANCELLED
    assert result.failure_category == TrainingFailureCategory.CANCELLED
    assert "incomplete" in result.reason
    assert "not promotable" in result.reason


def test_training_cost_report_exceeds_detects_budget_violations():
    budget = TrainingBudget(max_gpu_seconds=10, max_examples=100, max_wall_clock_seconds=60, max_storage_bytes=1000)
    over_budget = TrainingCostReport(gpu_seconds_used=20, examples_used=50, wall_clock_seconds=30, storage_bytes_used=500)
    violations = over_budget.exceeds(budget)
    assert violations == ["max_gpu_seconds"]

    under_budget = TrainingCostReport(gpu_seconds_used=5, examples_used=50, wall_clock_seconds=30, storage_bytes_used=500)
    assert under_budget.exceeds(budget) == []
