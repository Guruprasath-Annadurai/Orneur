"""
Artifact retention/eviction policy -- the direct fix for Phase 0.5's real
incident (two Novus artifacts removed via bare `ollama rm` with no registry
record). From Phase 1.1 forward, eviction must go through evict_artifact(),
which refuses to silently evict a PRODUCTION or rollback-target checkpoint
and always logs who/why/when.
"""
from __future__ import annotations

import pytest

from orca.registry.artifact_retention import (
    EVICTION_LOG_PATH,
    EvictionRefused,
    evict_artifact,
    read_eviction_log,
)
from orca.registry.checkpoint import ArtifactAvailability, CheckpointRecord
from orca.registry.evaluation_registry import EvaluationReport, evaluate_promotion
from orca.registry.model_registry import ModelRegistry


@pytest.fixture
def isolated_eviction_log(tmp_path, monkeypatch):
    log_path = tmp_path / "eviction_log.jsonl"
    import orca.registry.artifact_retention as retention_mod
    monkeypatch.setattr(retention_mod, "EVICTION_LOG_PATH", log_path)
    return log_path


def _make_checkpoint(**overrides):
    defaults = dict(
        checkpoint_id="evict-test", model_id="orneur-novus", run_id="r",
        step_or_epoch="e", base_model="x", dataset_manifest_ids=[],
        training_config_summary="x", optimizer_state_available=False,
        scheduler_state_available=False, tokenizer_identity="x",
        artifact_path="na", artifact_checksum="realhash",
        availability=ArtifactAvailability.LOCAL.value,
    )
    defaults.update(overrides)
    return CheckpointRecord(**defaults)


def test_eviction_without_registry_check_succeeds_and_logs(isolated_eviction_log, tmp_path, monkeypatch):
    import orca.registry.checkpoint as checkpoint_mod
    monkeypatch.setattr(checkpoint_mod, "CHECKPOINT_DIR", tmp_path)

    ckpt = _make_checkpoint()
    ckpt.save()

    result = evict_artifact(ckpt, reason="disk pressure", actor="test-script")
    assert result.availability == ArtifactAvailability.MISSING.value
    assert "disk pressure" in result.availability_note

    log = read_eviction_log()
    assert len(log) == 1
    assert log[0].checkpoint_id == "evict-test"
    assert log[0].reason == "disk pressure"
    assert log[0].actor == "test-script"
    assert log[0].availability_before == ArtifactAvailability.LOCAL.value
    assert log[0].checksum_preserved == "realhash"  # checksum survives the eviction, even though the file doesn't


def test_eviction_refused_for_production_checkpoint(isolated_eviction_log, tmp_path, monkeypatch):
    import orca.registry.checkpoint as checkpoint_mod
    monkeypatch.setattr(checkpoint_mod, "CHECKPOINT_DIR", tmp_path)

    reg = ModelRegistry(state_path=tmp_path / "state.json")
    ckpt = _make_checkpoint(checkpoint_id="prod-ckpt")
    ckpt.save()
    reg.register(ckpt, family="novus")

    good_report = EvaluationReport(
        evaluation_id="e1", checkpoint_id="prod-ckpt", family="novus",
        evaluator_version="x", dataset_version="x",
        metrics={"eval_accuracy": 90.0, "jailbreak_block_rate": 95.0, "bias_flag_rate": 1.0, "domain_eval": 90.0},
        acceptance_thresholds={},
    )
    evaluate_promotion(good_report)
    reg.promote("prod-ckpt", good_report)

    with pytest.raises(EvictionRefused):
        evict_artifact(ckpt, reason="disk pressure", actor="test-script", registry=reg)

    assert len(read_eviction_log()) == 0  # refused eviction must not be logged as having happened


def test_eviction_refused_for_rollback_target(isolated_eviction_log, tmp_path, monkeypatch):
    import orca.registry.checkpoint as checkpoint_mod
    monkeypatch.setattr(checkpoint_mod, "CHECKPOINT_DIR", tmp_path)

    reg = ModelRegistry(state_path=tmp_path / "state.json")

    def good_report(cid):
        r = EvaluationReport(
            evaluation_id=f"e-{cid}", checkpoint_id=cid, family="novus",
            evaluator_version="x", dataset_version="x",
            metrics={"eval_accuracy": 90.0, "jailbreak_block_rate": 95.0, "bias_flag_rate": 1.0, "domain_eval": 90.0},
            acceptance_thresholds={},
        )
        return evaluate_promotion(r)

    v1 = _make_checkpoint(checkpoint_id="v1")
    v1.save()
    reg.register(v1, family="novus")
    reg.promote("v1", good_report("v1"))

    v2 = _make_checkpoint(checkpoint_id="v2")
    v2.save()
    reg.register(v2, family="novus")
    reg.promote("v2", good_report("v2"))  # this retires v1 -> v1 becomes the rollback target

    assert reg.rollback_target("novus").checkpoint_id == "v1"

    with pytest.raises(EvictionRefused):
        evict_artifact(v1, reason="disk pressure", actor="test-script", registry=reg)


def test_eviction_force_overrides_protection(isolated_eviction_log, tmp_path, monkeypatch):
    import orca.registry.checkpoint as checkpoint_mod
    monkeypatch.setattr(checkpoint_mod, "CHECKPOINT_DIR", tmp_path)

    reg = ModelRegistry(state_path=tmp_path / "state.json")
    ckpt = _make_checkpoint(checkpoint_id="force-test")
    ckpt.save()
    reg.register(ckpt, family="novus")

    report = EvaluationReport(
        evaluation_id="e1", checkpoint_id="force-test", family="novus",
        evaluator_version="x", dataset_version="x",
        metrics={"eval_accuracy": 90.0, "jailbreak_block_rate": 95.0, "bias_flag_rate": 1.0, "domain_eval": 90.0},
        acceptance_thresholds={},
    )
    evaluate_promotion(report)
    reg.promote("force-test", report)

    # A deliberate, explicit human override -- must still work, but only via force=True.
    result = evict_artifact(ckpt, reason="explicit archival decision", actor="human:owner", registry=reg, force=True)
    assert result.availability == ArtifactAvailability.MISSING.value
    assert len(read_eviction_log()) == 1


def test_eviction_without_registry_arg_has_no_protection_check(isolated_eviction_log, tmp_path, monkeypatch):
    """Calling evict_artifact with registry=None (the default) performs no
    production/rollback check -- documents that the protection is opt-in
    via passing a registry, not a filesystem-level guarantee."""
    import orca.registry.checkpoint as checkpoint_mod
    monkeypatch.setattr(checkpoint_mod, "CHECKPOINT_DIR", tmp_path)
    ckpt = _make_checkpoint(checkpoint_id="no-registry-test")
    ckpt.save()
    result = evict_artifact(ckpt, reason="test", actor="test")
    assert result.availability == ArtifactAvailability.MISSING.value
