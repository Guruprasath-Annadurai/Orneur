"""
Artifact availability is a distinct axis from lifecycle_state -- a
checkpoint's METADATA existing must never be conflated with its WEIGHT
FILE being loadable. This is the direct fix for Phase 1's honest gap:
orca-core-dpo/orca-core were represented only via an ad-hoc checksum
sentinel string, not a real, checked field.
"""
from __future__ import annotations

import pytest

from orca.registry.checkpoint import ArtifactAvailability, CheckpointRecord, CorruptCheckpointError


def _make_checkpoint(**overrides):
    defaults = dict(
        checkpoint_id="avail-test", model_id="orneur-novus", run_id="r",
        step_or_epoch="e", base_model="x", dataset_manifest_ids=[],
        training_config_summary="x", optimizer_state_available=False,
        scheduler_state_available=False, tokenizer_identity="x",
        artifact_path="na", artifact_checksum="na",
    )
    defaults.update(overrides)
    return CheckpointRecord(**defaults)


def test_new_checkpoint_defaults_to_missing_not_local():
    """A checkpoint must never be assumed present -- only an explicit check sets LOCAL."""
    ckpt = _make_checkpoint()
    assert ckpt.availability == ArtifactAvailability.MISSING.value
    assert not ckpt.is_loadable()
    assert not ckpt.is_routable()


def test_verify_integrity_sets_local_on_success(tmp_path):
    from orca.registry.dataset_manifest import sha256_of_file
    artifact = tmp_path / "model.gguf"
    artifact.write_bytes(b"real weights")
    ckpt = _make_checkpoint(artifact_path=str(artifact), artifact_checksum=sha256_of_file(artifact))
    ckpt.verify_integrity()
    assert ckpt.availability == ArtifactAvailability.LOCAL.value
    assert ckpt.is_loadable()


def test_corrupt_artifact_is_not_loadable(tmp_path):
    from orca.registry.dataset_manifest import sha256_of_file
    artifact = tmp_path / "model.gguf"
    artifact.write_bytes(b"original")
    ckpt = _make_checkpoint(artifact_path=str(artifact), artifact_checksum=sha256_of_file(artifact))
    artifact.write_bytes(b"CORRUPTED")
    with pytest.raises(CorruptCheckpointError):
        ckpt.verify_integrity()
    assert not ckpt.is_loadable()


def test_missing_local_file_is_not_loadable_even_with_recorded_checksum(tmp_path):
    """
    The exact real-world case: orca-core-dpo has a recorded checksum but no
    local file. Metadata existing must not imply the weights are loadable.
    """
    ckpt = _make_checkpoint(artifact_path=str(tmp_path / "does_not_exist.gguf"), artifact_checksum="somehash")
    assert ckpt.verify_integrity() is False
    assert ckpt.availability == ArtifactAvailability.MISSING.value
    assert not ckpt.is_loadable()


def test_remote_recoverable_checkpoint_is_still_not_loadable():
    """
    REMOTE means "verified recoverable from a known source" -- this is
    orca-core-dpo's real, current state after Phase 1.1's recovery
    assessment. It must still not be treated as loadable without an
    explicit fetch step.
    """
    ckpt = _make_checkpoint(
        availability=ArtifactAvailability.REMOTE.value,
        recovery_source="kaggle:guruprasathannadurai/orca-core-dpo-merge-export-v1",
    )
    assert not ckpt.is_loadable()
    assert not ckpt.is_routable()


def test_refresh_availability_does_not_downgrade_remote_to_missing_on_no_local_file():
    """
    A checkpoint marked REMOTE (a deliberate, verified fact about a known
    recovery source) must not silently flip to MISSING just because
    refresh_availability() is called without the file present locally --
    that would erase the recovery work.
    """
    ckpt = _make_checkpoint(availability=ArtifactAvailability.REMOTE.value)
    ckpt.refresh_availability()
    assert ckpt.availability == ArtifactAvailability.REMOTE.value


def test_refresh_availability_sets_missing_for_a_plain_unverified_checkpoint(tmp_path):
    ckpt = _make_checkpoint(
        availability=ArtifactAvailability.MISSING.value,
        artifact_path=str(tmp_path / "gone.gguf"),
    )
    result = ckpt.refresh_availability()
    assert result == ArtifactAvailability.MISSING.value


def test_latest_good_checkpoint_can_require_loadable(monkeypatch, tmp_path):
    from orca.registry import checkpoint as checkpoint_mod
    monkeypatch.setattr(checkpoint_mod, "CHECKPOINT_DIR", tmp_path)

    remote_only = _make_checkpoint(
        checkpoint_id="remote-only", availability=ArtifactAvailability.REMOTE.value,
        created_at="2026-01-02T00:00:00Z",
    )
    remote_only.save()

    local_older = _make_checkpoint(
        checkpoint_id="local-older", availability=ArtifactAvailability.LOCAL.value,
        created_at="2026-01-01T00:00:00Z",
    )
    local_older.save()

    # Without require_loadable, the newer (but not-loadable) REMOTE one wins.
    latest_any = checkpoint_mod.latest_good_checkpoint("orneur-novus")
    assert latest_any.checkpoint_id == "remote-only"

    # With require_loadable, only the actually-loadable one is eligible.
    latest_loadable = checkpoint_mod.latest_good_checkpoint("orneur-novus", require_loadable=True)
    assert latest_loadable.checkpoint_id == "local-older"
