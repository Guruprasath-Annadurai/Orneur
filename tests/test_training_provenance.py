"""
Phase 21B reproducibility closure: orca.registry.provenance wires
TrainingConfig -> TrainingRunManifest -> CheckpointRecord ->
ModelRegistry without ever needing a GPU or the unsloth/torch/
transformers stack -- these tests exercise the full lifecycle, including
the failure path, entirely on CPU.
"""
from __future__ import annotations

import pytest

from orca.registry.checkpoint import CheckpointRecord
from orca.registry.model_registry import ModelRegistry
from orca.registry.model_spec import LifecycleState
from orca.registry.provenance import (
    complete_training_run,
    deterministic_run_id,
    fail_training_run,
    start_training_run,
)
from orca.registry.training_run import TrainingRunManifest
from orca.train.config import TrainingConfig


def test_deterministic_run_id_is_pure_and_reproducible():
    cfg = TrainingConfig.preset("nano")
    a = deterministic_run_id(cfg, nonce="fixed-nonce")
    b = deterministic_run_id(cfg, nonce="fixed-nonce")
    assert a == b
    assert a.startswith("run-")


def test_deterministic_run_id_changes_with_nonce():
    cfg = TrainingConfig.preset("nano")
    a = deterministic_run_id(cfg, nonce="n1")
    b = deterministic_run_id(cfg, nonce="n2")
    assert a != b


def test_start_training_run_creates_a_persisted_manifest():
    cfg = TrainingConfig.preset("nano")
    manifest = start_training_run(
        cfg, dataset_manifest_ids=["orneur-genesis-v2-v1"], hardware_info="test-cpu", run_id="run-test-1",
    )
    assert isinstance(manifest, TrainingRunManifest)
    assert manifest.run_id == "run-test-1"
    assert manifest.model_id == "orneur-genesis"
    assert manifest.base_model == cfg.base_model
    assert manifest.dataset_manifest_ids == ["orneur-genesis-v2-v1"]
    assert manifest.end_time is None
    assert manifest.failure_state is None

    # Persisted -- a fresh load reconstructs the same run.
    reloaded = TrainingRunManifest.load("run-test-1")
    assert reloaded.model_id == "orneur-genesis"


def test_start_training_run_fails_closed_for_manually_overridden_base_model():
    """The exact Phase 16 bypass class -- a canonical family config with
    its base_model manually overridden must never reach manifest
    creation at all."""
    cfg = TrainingConfig.preset("nano")
    cfg.base_model = "some/arbitrary-model"
    with pytest.raises(ValueError, match="canonical|family|override"):
        start_training_run(cfg, dataset_manifest_ids=[], hardware_info="test-cpu")


def test_start_training_run_fails_closed_for_unselected_aeternum():
    cfg = TrainingConfig.preset("ultra")
    with pytest.raises(ValueError, match="UNSELECTED_PROVISIONAL|no selected|None"):
        start_training_run(cfg, dataset_manifest_ids=[], hardware_info="test-cpu")


def test_complete_training_run_registers_checkpoint_at_experimental_only():
    """Training completion must never imply PROMOTABLE/PRODUCTION/
    AVAILABLE -- only ModelRegistry.promote() (gated on a passing
    evaluation report) can do that."""
    cfg = TrainingConfig.preset("nano")
    manifest = start_training_run(cfg, dataset_manifest_ids=[], hardware_info="test-cpu", run_id="run-complete-1")

    record = complete_training_run(
        manifest,
        checkpoint_id="genesis-test-checkpoint",
        artifact_path="/tmp/does-not-need-to-exist-for-this-test/merged",
        artifact_checksum="deadbeef",
        step_or_epoch="epoch=3",
        training_config_summary="QLoRA r=32",
        tokenizer_identity=cfg.base_model,
    )
    assert isinstance(record, CheckpointRecord)
    assert record.run_id == "run-complete-1"
    assert record.model_id == "orneur-genesis"
    assert record.base_model == cfg.base_model

    # Registered, but only at the registry's own default (EXPERIMENTAL) --
    # never PRODUCTION/PROMOTABLE as a side effect of training completion.
    registry = ModelRegistry()
    entry = registry.lookup("genesis-test-checkpoint")
    assert entry is not None
    assert entry.lifecycle_state == LifecycleState.EXPERIMENTAL.value
    assert registry.lookup_production("genesis") is None

    # Manifest correctly marked complete.
    reloaded = TrainingRunManifest.load("run-complete-1")
    assert reloaded.end_time is not None
    assert reloaded.failure_state is None
    assert reloaded.checkpoint_outputs == ["genesis-test-checkpoint"]


def test_finetune_train_wrapper_marks_manifest_failed_on_missing_dependencies():
    """CPU-safe, real (not mocked) end-to-end proof of the orchestration
    path: this test environment genuinely has no unsloth/trl/datasets/
    peft/bitsandbytes installed, so orca.train.finetune.train()'s real
    _check_deps() call genuinely raises ImportError -- proving the
    manifest-created-before-any-model-work / marked-failed-on-any-
    exception wiring end to end, without mocking anything and without
    ever touching a GPU. This is orchestration verification, not model
    training -- no CheckpointRecord is ever created on this path."""
    from orca.registry.training_run import list_runs
    from orca.train.config import TrainingConfig
    from orca.train.finetune import train

    cfg = TrainingConfig.preset("nano")
    with pytest.raises(ImportError, match="Missing training dependencies"):
        train(cfg, on_log=lambda _msg: None)

    runs = list_runs("orneur-genesis")
    assert len(runs) == 1
    assert runs[0].failure_state is not None
    assert "ImportError" in runs[0].failure_state
    assert runs[0].end_time is not None
    assert runs[0].checkpoint_outputs == []


def test_fail_training_run_never_creates_a_checkpoint():
    """A failure must never leave the registry looking as if a
    checkpoint succeeded -- no CheckpointRecord exists after a failure."""
    cfg = TrainingConfig.preset("nano")
    manifest = start_training_run(cfg, dataset_manifest_ids=[], hardware_info="test-cpu", run_id="run-fail-1")

    fail_training_run(manifest, "simulated CUDA OOM")

    reloaded = TrainingRunManifest.load("run-fail-1")
    assert reloaded.end_time is not None
    assert reloaded.failure_state == "simulated CUDA OOM"
    assert reloaded.checkpoint_outputs == []

    with pytest.raises(FileNotFoundError):
        CheckpointRecord.load("run-fail-1")

    registry = ModelRegistry()
    assert registry.lookup_production("genesis") is None
