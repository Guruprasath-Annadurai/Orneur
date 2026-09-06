"""
Tests for the model/dataset/checkpoint/evaluation registry lifecycle
(orca/registry/*). Uses an isolated ORCA_HOME per test via monkeypatch so
these never touch the real ~/.orca/registry/ state, matching the pattern
already used by tests/test_tools_security_scan.py.
"""
from __future__ import annotations

import json

import pytest

from orca.registry import checkpoint as checkpoint_mod
from orca.registry import dataset_manifest as dataset_mod
from orca.registry import evaluation_registry as eval_mod
from orca.registry import model_registry as registry_mod
from orca.registry import training_run as run_mod
from orca.registry.checkpoint import CheckpointRecord, CorruptCheckpointError
from orca.registry.dataset_manifest import DatasetManifest, sha256_of_file
from orca.registry.evaluation_registry import EvaluationReport, UNMEASURED, evaluate_promotion
from orca.registry.model_registry import ModelRegistry, PromotionDenied
from orca.registry.training_run import TrainingRunManifest


@pytest.fixture
def isolated_registry_dirs(tmp_path, monkeypatch):
    dataset_dir = tmp_path / "datasets"
    checkpoint_dir = tmp_path / "checkpoints"
    run_dir = tmp_path / "training_runs"
    eval_dir = tmp_path / "evaluations"
    for d in (dataset_dir, checkpoint_dir, run_dir, eval_dir):
        d.mkdir(parents=True)
    monkeypatch.setattr(dataset_mod, "DATASET_MANIFEST_DIR", dataset_dir)
    monkeypatch.setattr(checkpoint_mod, "CHECKPOINT_DIR", checkpoint_dir)
    monkeypatch.setattr(run_mod, "TRAINING_RUN_DIR", run_dir)
    monkeypatch.setattr(eval_mod, "EVALUATION_REGISTRY_DIR", eval_dir)
    return tmp_path


# ---------------------------------------------------------------- dataset ---

def test_dataset_manifest_round_trip(isolated_registry_dirs, tmp_path):
    train_file = tmp_path / "train.jsonl"
    eval_file = tmp_path / "eval.jsonl"
    train_file.write_text('{"text": "a"}\n')
    eval_file.write_text('{"text": "b"}\n')

    m = DatasetManifest(
        dataset_id="test-dataset",
        version="v1",
        purpose="unit test",
        source_paths=["fake.jsonl"],
        record_count=2,
        schema='{"text": str}',
        train_checksum=sha256_of_file(train_file),
        eval_checksum=sha256_of_file(eval_file),
        creation_code_sha="deadbeef",
        filters_applied="none",
        deduplication_result="0 exact duplicates",
        known_limitations=["small sample"],
    )
    m.save()
    loaded = DatasetManifest.load("test-dataset", "v1")
    assert loaded.record_count == 2
    assert loaded.known_limitations == ["small sample"]

    ok, msg = loaded.verify_against_files(train_file, eval_file)
    assert ok, msg


def test_dataset_manifest_detects_tampering(isolated_registry_dirs, tmp_path):
    train_file = tmp_path / "train.jsonl"
    eval_file = tmp_path / "eval.jsonl"
    train_file.write_text('{"text": "a"}\n')
    eval_file.write_text('{"text": "b"}\n')

    m = DatasetManifest(
        dataset_id="tamper-test", version="v1", purpose="x", source_paths=[],
        record_count=1, schema="x", train_checksum=sha256_of_file(train_file),
        eval_checksum=sha256_of_file(eval_file), creation_code_sha="x",
        filters_applied="x", deduplication_result="x",
    )
    m.save()

    train_file.write_text('{"text": "TAMPERED"}\n')
    ok, msg = m.verify_against_files(train_file, eval_file)
    assert not ok
    assert "mismatch" in msg


# -------------------------------------------------------------- checkpoint --

def test_checkpoint_round_trip_and_integrity(isolated_registry_dirs, tmp_path):
    artifact = tmp_path / "model.gguf"
    artifact.write_bytes(b"fake weights")

    rec = CheckpointRecord(
        checkpoint_id="test-checkpoint-v1",
        model_id="orneur-novus",
        run_id="run-1",
        step_or_epoch="epoch-3",
        base_model="unsloth/Meta-Llama-3.1-8B-Instruct",
        dataset_manifest_ids=["test-dataset-v1"],
        training_config_summary="lr=1e-4",
        optimizer_state_available=False,
        scheduler_state_available=False,
        tokenizer_identity="unsloth/Meta-Llama-3.1-8B-Instruct",
        artifact_path=str(artifact),
        artifact_checksum=sha256_of_file(artifact),
    )
    rec.save()

    loaded = CheckpointRecord.load("test-checkpoint-v1")
    assert loaded.verify_integrity() is True
    assert loaded.validation_state == "VALID"


def test_checkpoint_rejects_corrupt_artifact(isolated_registry_dirs, tmp_path):
    artifact = tmp_path / "model.gguf"
    artifact.write_bytes(b"original weights")
    rec = CheckpointRecord(
        checkpoint_id="corrupt-test", model_id="orneur-novus", run_id="r",
        step_or_epoch="e", base_model="x", dataset_manifest_ids=[],
        training_config_summary="x", optimizer_state_available=False,
        scheduler_state_available=False, tokenizer_identity="x",
        artifact_path=str(artifact), artifact_checksum=sha256_of_file(artifact),
    )
    rec.save()

    artifact.write_bytes(b"CORRUPTED")  # simulate bit-rot / bad transfer
    with pytest.raises(CorruptCheckpointError):
        rec.verify_integrity()


def test_latest_good_checkpoint_skips_corrupt(isolated_registry_dirs, tmp_path):
    from orca.registry.checkpoint import latest_good_checkpoint

    for i, ts in enumerate(["2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"]):
        rec = CheckpointRecord(
            checkpoint_id=f"ckpt-{i}", model_id="orneur-novus", run_id="r",
            step_or_epoch="e", base_model="x", dataset_manifest_ids=[],
            training_config_summary="x", optimizer_state_available=False,
            scheduler_state_available=False, tokenizer_identity="x",
            artifact_path="na", artifact_checksum="na", created_at=ts,
            validation_state="CORRUPT" if i == 1 else "VALID",
        )
        rec.save()

    latest = latest_good_checkpoint("orneur-novus")
    assert latest.checkpoint_id == "ckpt-0"  # the newer one (ckpt-1) is corrupt, must be skipped


# ------------------------------------------------------------ training run --

def test_training_run_manifest_lifecycle(isolated_registry_dirs):
    run = TrainingRunManifest(
        run_id="run-test-1", model_id="orneur-novus", base_model="x",
        dataset_manifest_ids=["d1"], training_config={"lr": 1e-4},
        hyperparameters={"epochs": 3}, seed=42, precision="fp16",
        hardware_info="Kaggle T4",
    )
    run.save()
    run.mark_complete("test-checkpoint-v1")

    loaded = TrainingRunManifest.load("run-test-1")
    assert loaded.checkpoint_outputs == ["test-checkpoint-v1"]
    assert loaded.end_time is not None
    assert loaded.failure_state is None


def test_training_run_records_failure(isolated_registry_dirs):
    run = TrainingRunManifest(
        run_id="run-fail-1", model_id="orneur-novus", base_model="x",
        dataset_manifest_ids=[], training_config={}, hyperparameters={},
        seed=None, precision="fp16", hardware_info="x",
    )
    run.save()
    run.mark_failed("OOM at step 12")
    loaded = TrainingRunManifest.load("run-fail-1")
    assert loaded.failure_state == "OOM at step 12"


# --------------------------------------------------------- evaluation gate --

def test_promotion_denied_when_metric_unmeasured(isolated_registry_dirs):
    report = EvaluationReport(
        evaluation_id="eval-1", checkpoint_id="ckpt-x", family="novus",
        evaluator_version="x", dataset_version="x",
        metrics={"jailbreak_block_rate": 95.0, "bias_flag_rate": 5.0},  # accuracy/domain_eval missing
        acceptance_thresholds={},
    )
    result = evaluate_promotion(report)
    assert result.pass_fail_status == "NOT_PROMOTABLE"
    assert any("UNMEASURED" in r for r in result.failure_reasons)


def test_promotion_denied_when_jailbreak_below_threshold(isolated_registry_dirs):
    """Mirrors the real Novus checkpoint's actual, current state: 70% strict
    jailbreak vs. the 92% required for 'core' -- must NOT be promotable."""
    report = EvaluationReport(
        evaluation_id="eval-novus-real", checkpoint_id="orca-core-combined-v2",
        family="novus", evaluator_version="x", dataset_version="x",
        metrics={
            "eval_accuracy": 75.0, "jailbreak_block_rate": 70.0,
            "bias_flag_rate": 12.5, "domain_eval": 80.0,
        },
        acceptance_thresholds={},
    )
    result = evaluate_promotion(report)
    assert result.pass_fail_status == "NOT_PROMOTABLE"
    assert any("jailbreak_block_rate" in r for r in result.failure_reasons)


def test_promotion_allowed_when_all_thresholds_clear(isolated_registry_dirs):
    report = EvaluationReport(
        evaluation_id="eval-pass", checkpoint_id="ckpt-good", family="novus",
        evaluator_version="x", dataset_version="x",
        metrics={
            "eval_accuracy": 80.0, "jailbreak_block_rate": 95.0,
            "bias_flag_rate": 5.0, "domain_eval": 90.0,
        },
        acceptance_thresholds={},
    )
    result = evaluate_promotion(report)
    assert result.pass_fail_status == "PROMOTABLE"
    assert result.failure_reasons == []


# ------------------------------------------------------------ model registry

def test_register_lookup_and_promote(isolated_registry_dirs, tmp_path):
    state_path = tmp_path / "registry_state.json"
    reg = ModelRegistry(state_path=state_path)

    artifact = tmp_path / "model.gguf"
    artifact.write_bytes(b"weights")
    ckpt = CheckpointRecord(
        checkpoint_id="promo-test", model_id="orneur-novus", run_id="r",
        step_or_epoch="e", base_model="x", dataset_manifest_ids=[],
        training_config_summary="x", optimizer_state_available=False,
        scheduler_state_available=False, tokenizer_identity="x",
        artifact_path=str(artifact), artifact_checksum="x",
    )
    entry = reg.register(ckpt, family="novus")
    assert entry.lifecycle_state == "EXPERIMENTAL"
    assert reg.lookup("promo-test") is not None

    good_report = EvaluationReport(
        evaluation_id="e1", checkpoint_id="promo-test", family="novus",
        evaluator_version="x", dataset_version="x",
        metrics={"eval_accuracy": 90.0, "jailbreak_block_rate": 95.0, "bias_flag_rate": 1.0, "domain_eval": 90.0},
        acceptance_thresholds={},
    )
    evaluate_promotion(good_report)
    promoted = reg.promote("promo-test", good_report, promoted_by="test")
    assert promoted.lifecycle_state == "PRODUCTION"
    assert reg.lookup_production("novus").checkpoint_id == "promo-test"


def test_promote_refuses_when_not_promotable(isolated_registry_dirs, tmp_path):
    state_path = tmp_path / "registry_state.json"
    reg = ModelRegistry(state_path=state_path)
    ckpt = CheckpointRecord(
        checkpoint_id="bad-ckpt", model_id="orneur-novus", run_id="r",
        step_or_epoch="e", base_model="x", dataset_manifest_ids=[],
        training_config_summary="x", optimizer_state_available=False,
        scheduler_state_available=False, tokenizer_identity="x",
        artifact_path="na", artifact_checksum="na",
    )
    reg.register(ckpt, family="novus")

    bad_report = EvaluationReport(
        evaluation_id="e2", checkpoint_id="bad-ckpt", family="novus",
        evaluator_version="x", dataset_version="x",
        metrics={"jailbreak_block_rate": 70.0},  # rest UNMEASURED
        acceptance_thresholds={},
    )
    evaluate_promotion(bad_report)
    with pytest.raises(PromotionDenied):
        reg.promote("bad-ckpt", bad_report)

    # Confirm it truly was never promoted (this is the actual enforcement check)
    assert reg.lookup("bad-ckpt").lifecycle_state != "PRODUCTION"
    assert reg.lookup_production("novus") is None


def test_rollback_target_after_promotion_and_supersession(isolated_registry_dirs, tmp_path):
    state_path = tmp_path / "registry_state.json"
    reg = ModelRegistry(state_path=state_path)

    def make_ckpt(cid):
        return CheckpointRecord(
            checkpoint_id=cid, model_id="orneur-novus", run_id="r", step_or_epoch="e",
            base_model="x", dataset_manifest_ids=[], training_config_summary="x",
            optimizer_state_available=False, scheduler_state_available=False,
            tokenizer_identity="x", artifact_path="na", artifact_checksum="na",
        )

    def good_report(cid):
        r = EvaluationReport(
            evaluation_id=f"eval-{cid}", checkpoint_id=cid, family="novus",
            evaluator_version="x", dataset_version="x",
            metrics={"eval_accuracy": 90.0, "jailbreak_block_rate": 95.0, "bias_flag_rate": 1.0, "domain_eval": 90.0},
            acceptance_thresholds={},
        )
        return evaluate_promotion(r)

    reg.register(make_ckpt("v1"), family="novus")
    reg.promote("v1", good_report("v1"))

    reg.register(make_ckpt("v2"), family="novus")
    reg.promote("v2", good_report("v2"))

    assert reg.lookup_production("novus").checkpoint_id == "v2"
    assert reg.lookup("v1").lifecycle_state == "RETIRED"

    target = reg.rollback_target("novus")
    assert target.checkpoint_id == "v1"


def test_aeternum_absent_checkpoint_cannot_be_routed(isolated_registry_dirs, tmp_path):
    """
    The registry must return None for a family with no promoted checkpoint
    (Aeternum today) -- never substitute a different family's model or a
    fabricated placeholder that a caller might mistake for a real one.
    """
    state_path = tmp_path / "registry_state.json"
    reg = ModelRegistry(state_path=state_path)
    reg.mark_family_absent("aeternum")  # registers the family definition only

    assert reg.lookup_production("aeternum") is None
    assert reg.lookup_latest_candidate("aeternum") is None


def test_mark_family_absent_rejects_unknown_family(isolated_registry_dirs, tmp_path):
    reg = ModelRegistry(state_path=tmp_path / "state.json")
    with pytest.raises(ValueError):
        reg.mark_family_absent("not-a-real-family")
