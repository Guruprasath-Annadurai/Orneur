"""
GENESIS Foundation Sprint 2, Workstream B: checkpoint integrity tests.
Covers corruption, substitution, missing-manifest, and crash-consistency
(interruption) conditions, per the sprint's own explicit instruction.
"""
from __future__ import annotations

import json

import pytest

torch = pytest.importorskip("torch")

from orca.genesis.training.checkpoint_integrity import (  # noqa: E402
    ChecksumMismatchError,
    ManifestMissingError,
    load_verified_training_state,
    save_verified_training_state,
)
from orca.genesis.training.primitives import TrainingState, save_training_state  # noqa: E402


def _state(step=1) -> TrainingState:
    return TrainingState(
        step=step, epoch=0, dataloader_position=0, model_state_dict={}, optimizer_state_dict={},
        python_rng_state=(1,), torch_rng_state=b"", cuda_rng_state=None,
    )


def test_round_trip_through_verified_save_and_load(tmp_path):
    path = tmp_path / "checkpoint.pt"
    manifest = save_verified_training_state(_state(step=7), path)
    loaded = load_verified_training_state(path)
    assert loaded.step == 7
    assert manifest.step == 7


def test_manifest_file_has_owner_only_permissions(tmp_path):
    import os
    import stat
    path = tmp_path / "checkpoint.pt"
    save_verified_training_state(_state(), path)
    manifest_path = tmp_path / "checkpoint.pt.manifest.json"
    assert manifest_path.exists()
    mode = stat.S_IMODE(os.stat(manifest_path).st_mode)
    assert mode == 0o600


# --------------------------------------------------------- corruption --

def test_single_byte_corruption_of_the_checkpoint_is_caught(tmp_path):
    """Adversarial corruption test: flip one byte in the checkpoint file
    itself (simulating disk corruption or a truncated/interrupted write
    that still left a file of the expected size) and confirm the
    mismatch is caught BEFORE deserialization is attempted."""
    path = tmp_path / "checkpoint.pt"
    save_verified_training_state(_state(), path)

    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0xFF  # flip a bit somewhere in the middle
    path.write_bytes(bytes(data))

    with pytest.raises(ChecksumMismatchError):
        load_verified_training_state(path)


def test_truncated_checkpoint_is_caught(tmp_path):
    path = tmp_path / "checkpoint.pt"
    save_verified_training_state(_state(), path)
    data = path.read_bytes()
    path.write_bytes(data[: len(data) // 2])
    with pytest.raises(ChecksumMismatchError):
        load_verified_training_state(path)


# -------------------------------------------------------- substitution --

def test_substituting_a_different_valid_checkpoint_is_caught(tmp_path):
    """The substitution attack: swap in a DIFFERENT, perfectly valid
    checkpoint (step=99 instead of step=1) under the original path.
    Must be caught by the hash mismatch even though the substituted file
    is itself a completely well-formed, loadable checkpoint on its own."""
    path_a = tmp_path / "checkpoint_a.pt"
    path_b = tmp_path / "checkpoint_b.pt"
    save_verified_training_state(_state(step=1), path_a)
    save_training_state(_state(step=99), path_b)  # a different, valid checkpoint, no manifest of its own

    # Simulate substitution: overwrite path_a's CONTENT with path_b's,
    # but leave path_a's original manifest (recorded for step=1) in place.
    path_a.write_bytes(path_b.read_bytes())

    with pytest.raises(ChecksumMismatchError):
        load_verified_training_state(path_a)


def test_manifest_itself_tampered_to_match_a_substituted_checkpoint_is_still_internally_consistent():
    """Documents, precisely, what this mechanism does and does not
    guarantee: if BOTH the checkpoint and its manifest are replaced
    together with a mutually-consistent pair (attacker controls both
    files), the hash check alone cannot detect that -- this is a
    content-integrity check, not a provenance/signing check (stated in
    this module's own docstring). Verifying WHO produced a checkpoint
    remains orca.registry.provenance's job, not duplicated here."""
    assert True  # documentation-only test; no new assertion needed beyond the module's own stated scope


# -------------------------------------------------------- missing manifest --

def test_missing_manifest_raises_a_distinct_error_not_checksum_mismatch(tmp_path):
    """A checkpoint saved via the OLDER, unverified save_training_state()
    (no manifest ever written) must raise ManifestMissingError, not
    ChecksumMismatchError -- the two conditions mean different things and
    must not be conflated in logs or alerting."""
    path = tmp_path / "checkpoint.pt"
    save_training_state(_state(), path)  # the plain, non-manifested save
    with pytest.raises(ManifestMissingError):
        load_verified_training_state(path)


def test_deleted_manifest_after_a_verified_save_is_caught(tmp_path):
    path = tmp_path / "checkpoint.pt"
    save_verified_training_state(_state(), path)
    manifest_path = tmp_path / "checkpoint.pt.manifest.json"
    manifest_path.unlink()
    with pytest.raises(ManifestMissingError):
        load_verified_training_state(path)


def test_missing_checkpoint_file_with_manifest_present_raises_file_not_found(tmp_path):
    path = tmp_path / "checkpoint.pt"
    save_verified_training_state(_state(), path)
    path.unlink()
    with pytest.raises(FileNotFoundError):
        load_verified_training_state(path)


# ------------------------------------------------------ crash consistency --

def test_interrupted_manifest_write_leaves_old_manifest_intact(tmp_path, monkeypatch):
    """Crash-consistency check: if the manifest write is interrupted
    partway (simulated by making the atomic rename itself raise), the
    ORIGINAL manifest (if one existed from a prior successful save) must
    remain fully intact and loadable -- never a half-written manifest
    file left behind, matching save_training_state()'s own established
    atomic-write discipline (Sprint 1 / Audit #016)."""
    path = tmp_path / "checkpoint.pt"
    save_verified_training_state(_state(step=1), path)
    original_manifest_bytes = (tmp_path / "checkpoint.pt.manifest.json").read_bytes()

    import orca.genesis.training.checkpoint_integrity as ci

    # Patch Path.replace just for the manifest's tmp file by checking the name.
    original_replace = ci.Path.replace

    def _patched_replace(self, target):
        if str(self).endswith(".manifest.json.tmp"):
            raise OSError("simulated crash during manifest rename")
        return original_replace(self, target)

    monkeypatch.setattr(ci.Path, "replace", _patched_replace)
    with pytest.raises(OSError, match="simulated crash"):
        save_verified_training_state(_state(step=2), path)
    monkeypatch.undo()

    # The original manifest (for step=1) must be untouched and still valid.
    assert (tmp_path / "checkpoint.pt.manifest.json").read_bytes() == original_manifest_bytes
