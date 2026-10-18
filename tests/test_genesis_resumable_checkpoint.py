"""
GENESIS Native Learning Engine, Phase 1, Workstream 3 tests:
`orca.genesis.training.resumable_checkpoint`. Bounded, CPU-only,
synthetic model/data only.

Includes Antigravity Audit #074 remediation regressions for AUDIT-P0-03
(partial-accumulation resume divergence) and AUDIT-P0-04 (sidecar
manifest integrity) -- the original audit evidence is preserved,
unmodified, in `tests/test_native_learning_engine_adversarial_audit.py`.
"""
from __future__ import annotations

import os

import pytest

torch = pytest.importorskip("torch")

import orca.config as orca_config  # noqa: E402
from orca.genesis.model.config import GenesisModelConfig  # noqa: E402
from orca.genesis.model.transformer import GenesisTransformer  # noqa: E402
from orca.genesis.training.learning_step import ExecutionCapability, TrainingStepConfig, TrainingStepEngine, set_deterministic_seed  # noqa: E402
from orca.genesis.training.primitives import TrainingState  # noqa: E402
from orca.genesis.training.resumable_checkpoint import (  # noqa: E402
    ChecksumMismatchError,
    DatasetIdentity,
    MidAccumulationCheckpointError,
    ResumableManifestTamperedError,
    ResumeEquivalenceError,
    compute_config_fingerprint,
    restore_resumable_checkpoint,
    save_resumable_checkpoint,
)

MODEL_CFG = GenesisModelConfig(vocab_size=48, d_model=16, n_layers=2, n_heads=2, n_kv_heads=1, d_ff=32, max_seq_len=16)
STEP_CFG = TrainingStepConfig(grad_accum_steps=1, warmup_steps=2, total_steps=20, seed=7)
FINGERPRINT = compute_config_fingerprint(MODEL_CFG, STEP_CFG)
DATASET_IDENTITY = DatasetIdentity(dataset_manifest_id="m1", dataset_content_digest="d" * 64, tokenizer_digest="t" * 64)
KEY = b"test-only-integrity-key-not-a-founder-key-32b!!"
TEST_CAP = ExecutionCapability.for_unchecked_synthetic_test()


@pytest.fixture(autouse=True)
def _isolate_checkpoint_ledger(tmp_path, monkeypatch):
    """AUDIT-075: the anti-rollback ledger lives under `orca.config
    .ORCA_HOME`, deliberately OUTSIDE the checkpoint directory a test's
    own `tmp_path` controls -- so it must be isolated per-test here, the
    same way the Audit #075 adversarial suite isolates it, or every
    test sharing a literal `run_id` string would see each other's
    ledger entries."""
    monkeypatch.setattr(orca_config, "ORCA_HOME", tmp_path / "ornhome")


def _build_engine_and_run_steps(n: int, seed: int = 7, step_cfg: TrainingStepConfig = STEP_CFG):
    set_deterministic_seed(seed)
    model = GenesisTransformer(MODEL_CFG)
    engine = TrainingStepEngine(model, step_cfg)
    torch.manual_seed(999)
    batch = torch.randint(0, MODEL_CFG.vocab_size, (2, 6))
    for _ in range(n):
        engine.step(batch, batch.clone(), capability=TEST_CAP)
    return engine, batch


def test_save_and_restore_round_trip_exact_fields(tmp_path):
    engine, batch = _build_engine_and_run_steps(3)
    ts = TrainingState.capture(step=engine.global_step, epoch=0, dataloader_position=0, model=engine.model, optimizer=engine.optimizer)
    path = tmp_path / "ckpt.pt"
    save_resumable_checkpoint(
        path=path, training_state=ts, global_step=engine.global_step, microbatch_in_cycle=engine.microbatch_in_cycle,
        sampler_position=17, sampler_seed=7, sampler_num_blocks=500,
        config_fingerprint=FINGERPRINT, dataset_identity=DATASET_IDENTITY, integrity_key=KEY, run_id="test-run-fixture",
    )
    restored = restore_resumable_checkpoint(
        path=path, expected_config_fingerprint=FINGERPRINT, expected_dataset_identity=DATASET_IDENTITY,
        expected_sampler_seed=7, expected_sampler_num_blocks=500, integrity_key=KEY, run_id="test-run-fixture",
    )
    assert restored.global_step == engine.global_step
    assert restored.microbatch_in_cycle == engine.microbatch_in_cycle
    assert restored.sampler_position == 17


def test_resumed_training_is_bit_identical_to_uninterrupted_training(tmp_path):
    # Uninterrupted: 5 steps straight (grad_accum_steps=1, so every step is a cycle boundary).
    engine_full, batch = _build_engine_and_run_steps(0)
    losses_full = [engine_full.step(batch, batch.clone(), capability=TEST_CAP).microbatch_loss for _ in range(5)]

    # Interrupted: 2 steps, checkpoint AT the cycle boundary, restore into a fresh engine, 3 more steps.
    engine_a, batch_a = _build_engine_and_run_steps(0)
    assert torch.equal(batch_a, batch)
    losses_a = [engine_a.step(batch_a, batch_a.clone(), capability=TEST_CAP).microbatch_loss for _ in range(2)]
    assert engine_a.microbatch_in_cycle == 0  # grad_accum_steps=1 -- every completed step is a safe boundary
    ts = TrainingState.capture(step=engine_a.global_step, epoch=0, dataloader_position=0, model=engine_a.model, optimizer=engine_a.optimizer)
    path = tmp_path / "ckpt.pt"
    save_resumable_checkpoint(
        path=path, training_state=ts, global_step=engine_a.global_step, microbatch_in_cycle=engine_a.microbatch_in_cycle,
        sampler_position=0, sampler_seed=7, sampler_num_blocks=500,
        config_fingerprint=FINGERPRINT, dataset_identity=DATASET_IDENTITY, integrity_key=KEY, run_id="test-run-fixture",
    )

    set_deterministic_seed(7)
    model_b = GenesisTransformer(MODEL_CFG)
    engine_b = TrainingStepEngine(model_b, STEP_CFG)
    restored = restore_resumable_checkpoint(
        path=path, expected_config_fingerprint=FINGERPRINT, expected_dataset_identity=DATASET_IDENTITY,
        expected_sampler_seed=7, expected_sampler_num_blocks=500, integrity_key=KEY, run_id="test-run-fixture",
    )
    restored.training_state.restore(model=model_b, optimizer=engine_b.optimizer)
    engine_b.global_step = restored.global_step
    engine_b.microbatch_in_cycle = restored.microbatch_in_cycle

    losses_b = losses_a + [engine_b.step(batch_a, batch_a.clone(), capability=TEST_CAP).microbatch_loss for _ in range(3)]

    assert len(losses_full) == len(losses_b) == 5
    for lf, lb in zip(losses_full, losses_b):
        assert lf == pytest.approx(lb, abs=1e-5), "resumed training diverged from uninterrupted training"


def test_restore_rejects_a_different_config_fingerprint(tmp_path):
    engine, batch = _build_engine_and_run_steps(1)
    ts = TrainingState.capture(step=engine.global_step, epoch=0, dataloader_position=0, model=engine.model, optimizer=engine.optimizer)
    path = tmp_path / "ckpt.pt"
    save_resumable_checkpoint(
        path=path, training_state=ts, global_step=engine.global_step, microbatch_in_cycle=engine.microbatch_in_cycle,
        sampler_position=0, sampler_seed=7, sampler_num_blocks=500,
        config_fingerprint=FINGERPRINT, dataset_identity=DATASET_IDENTITY, integrity_key=KEY, run_id="test-run-fixture",
    )
    with pytest.raises(ResumeEquivalenceError):
        restore_resumable_checkpoint(
            path=path, expected_config_fingerprint="a-different-fingerprint", expected_dataset_identity=DATASET_IDENTITY,
            expected_sampler_seed=7, expected_sampler_num_blocks=500, integrity_key=KEY, run_id="test-run-fixture",
        )


def test_restore_rejects_a_different_dataset_identity(tmp_path):
    engine, batch = _build_engine_and_run_steps(1)
    ts = TrainingState.capture(step=engine.global_step, epoch=0, dataloader_position=0, model=engine.model, optimizer=engine.optimizer)
    path = tmp_path / "ckpt.pt"
    save_resumable_checkpoint(
        path=path, training_state=ts, global_step=engine.global_step, microbatch_in_cycle=engine.microbatch_in_cycle,
        sampler_position=0, sampler_seed=7, sampler_num_blocks=500,
        config_fingerprint=FINGERPRINT, dataset_identity=DATASET_IDENTITY, integrity_key=KEY, run_id="test-run-fixture",
    )
    different = DatasetIdentity(dataset_manifest_id="different", dataset_content_digest="e" * 64, tokenizer_digest="t" * 64)
    with pytest.raises(ResumeEquivalenceError):
        restore_resumable_checkpoint(
            path=path, expected_config_fingerprint=FINGERPRINT, expected_dataset_identity=different,
            expected_sampler_seed=7, expected_sampler_num_blocks=500, integrity_key=KEY, run_id="test-run-fixture",
        )


def test_restore_rejects_a_tampered_checkpoint_content(tmp_path):
    engine, batch = _build_engine_and_run_steps(1)
    ts = TrainingState.capture(step=engine.global_step, epoch=0, dataloader_position=0, model=engine.model, optimizer=engine.optimizer)
    path = tmp_path / "ckpt.pt"
    save_resumable_checkpoint(
        path=path, training_state=ts, global_step=engine.global_step, microbatch_in_cycle=engine.microbatch_in_cycle,
        sampler_position=0, sampler_seed=7, sampler_num_blocks=500,
        config_fingerprint=FINGERPRINT, dataset_identity=DATASET_IDENTITY, integrity_key=KEY, run_id="test-run-fixture",
    )
    data = bytearray(path.read_bytes())
    data[0] ^= 0xFF
    path.write_bytes(bytes(data))
    with pytest.raises(ChecksumMismatchError):
        restore_resumable_checkpoint(
            path=path, expected_config_fingerprint=FINGERPRINT, expected_dataset_identity=DATASET_IDENTITY,
            expected_sampler_seed=7, expected_sampler_num_blocks=500, integrity_key=KEY, run_id="test-run-fixture",
        )


def test_restore_rejects_a_missing_resumable_manifest(tmp_path):
    """An incomplete/failed checkpoint (e.g. only the inner TrainingState
    was ever saved, this module's own sidecar manifest never written)
    must never be silently treated as a valid, trusted, resumable
    artifact."""
    engine, batch = _build_engine_and_run_steps(1)
    ts = TrainingState.capture(step=engine.global_step, epoch=0, dataloader_position=0, model=engine.model, optimizer=engine.optimizer)
    from orca.genesis.training.primitives import save_training_state
    path = tmp_path / "ckpt.pt"
    save_training_state(ts, path)  # the inner state only -- no resumable sidecar manifest
    with pytest.raises(ResumableManifestTamperedError):
        restore_resumable_checkpoint(
            path=path, expected_config_fingerprint=FINGERPRINT, expected_dataset_identity=DATASET_IDENTITY,
            expected_sampler_seed=7, expected_sampler_num_blocks=500, integrity_key=KEY, run_id="test-run-fixture",
        )


def test_config_fingerprint_is_order_sensitive_and_deterministic():
    f1 = compute_config_fingerprint(MODEL_CFG, STEP_CFG)
    f2 = compute_config_fingerprint(MODEL_CFG, STEP_CFG)
    assert f1 == f2
    f3 = compute_config_fingerprint(STEP_CFG, MODEL_CFG)  # swapped order
    assert f1 != f3


# ==================================================================================
# Antigravity Audit #074 remediation: AUDIT-P0-03 (partial-accumulation resume)
# ==================================================================================

def test_p0_03_saving_mid_accumulation_cycle_is_rejected_not_silently_accepted(tmp_path):
    step_cfg = TrainingStepConfig(grad_accum_steps=3, warmup_steps=2, total_steps=20, seed=11)
    fp = compute_config_fingerprint(MODEL_CFG, step_cfg)
    engine, batch = _build_engine_and_run_steps(0, seed=11, step_cfg=step_cfg)
    engine.step(batch, batch.clone(), capability=TEST_CAP)  # microbatch 0 of 3 -- cycle incomplete
    assert engine.microbatch_in_cycle == 1
    ts = TrainingState.capture(step=engine.global_step, epoch=0, dataloader_position=0, model=engine.model, optimizer=engine.optimizer)
    with pytest.raises(MidAccumulationCheckpointError):
        save_resumable_checkpoint(
            path=tmp_path / "ckpt.pt", training_state=ts, global_step=engine.global_step,
            microbatch_in_cycle=engine.microbatch_in_cycle, sampler_position=0, sampler_seed=11,
            sampler_num_blocks=10, config_fingerprint=fp, dataset_identity=DATASET_IDENTITY, integrity_key=KEY, run_id="test-run-fixture",
        )
    assert not (tmp_path / "ckpt.pt").exists(), "no checkpoint file should be left behind by a rejected save"


def test_p0_03_saving_exactly_at_a_completed_cycle_boundary_is_accepted(tmp_path):
    step_cfg = TrainingStepConfig(grad_accum_steps=3, warmup_steps=2, total_steps=20, seed=11)
    fp = compute_config_fingerprint(MODEL_CFG, step_cfg)
    engine, batch = _build_engine_and_run_steps(0, seed=11, step_cfg=step_cfg)
    for _ in range(3):  # complete the full cycle
        engine.step(batch, batch.clone(), capability=TEST_CAP)
    assert engine.microbatch_in_cycle == 0
    ts = TrainingState.capture(step=engine.global_step, epoch=0, dataloader_position=0, model=engine.model, optimizer=engine.optimizer)
    manifest = save_resumable_checkpoint(
        path=tmp_path / "ckpt.pt", training_state=ts, global_step=engine.global_step,
        microbatch_in_cycle=engine.microbatch_in_cycle, sampler_position=0, sampler_seed=11,
        sampler_num_blocks=10, config_fingerprint=fp, dataset_identity=DATASET_IDENTITY, integrity_key=KEY, run_id="test-run-fixture",
    )
    assert manifest.microbatch_in_cycle == 0


def test_p0_03_resumed_training_with_grad_accum_matches_uninterrupted_bit_identically(tmp_path):
    """The directive's own required interruption test "before and after
    gradient accumulation, optimizer update, scheduler advancement" --
    with grad_accum_steps > 1, checkpointing only at completed cycle
    boundaries, and comparing full weights/losses against an
    uninterrupted run."""
    step_cfg = TrainingStepConfig(grad_accum_steps=2, warmup_steps=2, total_steps=20, seed=5)
    fp = compute_config_fingerprint(MODEL_CFG, step_cfg)

    engine_full, batch = _build_engine_and_run_steps(0, seed=5, step_cfg=step_cfg)
    for _ in range(6):  # 3 complete cycles
        engine_full.step(batch, batch.clone(), capability=TEST_CAP)
    weights_full = {n: p.clone() for n, p in engine_full.model.named_parameters()}

    engine_a, batch_a = _build_engine_and_run_steps(0, seed=5, step_cfg=step_cfg)
    for _ in range(4):  # 2 complete cycles -- a safe boundary
        engine_a.step(batch_a, batch_a.clone(), capability=TEST_CAP)
    assert engine_a.microbatch_in_cycle == 0
    ts = TrainingState.capture(step=engine_a.global_step, epoch=0, dataloader_position=0, model=engine_a.model, optimizer=engine_a.optimizer)
    path = tmp_path / "ckpt.pt"
    save_resumable_checkpoint(
        path=path, training_state=ts, global_step=engine_a.global_step, microbatch_in_cycle=0,
        sampler_position=0, sampler_seed=5, sampler_num_blocks=10,
        config_fingerprint=fp, dataset_identity=DATASET_IDENTITY, integrity_key=KEY, run_id="test-run-fixture",
    )

    set_deterministic_seed(5)
    model_b = GenesisTransformer(MODEL_CFG)
    engine_b = TrainingStepEngine(model_b, step_cfg)
    restored = restore_resumable_checkpoint(
        path=path, expected_config_fingerprint=fp, expected_dataset_identity=DATASET_IDENTITY,
        expected_sampler_seed=5, expected_sampler_num_blocks=10, integrity_key=KEY, run_id="test-run-fixture",
    )
    restored.training_state.restore(model=model_b, optimizer=engine_b.optimizer)
    engine_b.global_step = restored.global_step
    engine_b.microbatch_in_cycle = restored.microbatch_in_cycle
    for _ in range(2):  # the remaining 1 cycle (2 microbatches)
        engine_b.step(batch_a, batch_a.clone(), capability=TEST_CAP)

    for n in weights_full:
        assert torch.allclose(weights_full[n], dict(engine_b.model.named_parameters())[n], atol=1e-6), f"parameter {n} diverged"


# ==================================================================================
# Antigravity Audit #074 remediation: AUDIT-P0-04 (sidecar manifest integrity)
# ==================================================================================

def test_p0_04_tampered_global_step_is_rejected(tmp_path):
    engine, batch = _build_engine_and_run_steps(1)
    ts = TrainingState.capture(step=engine.global_step, epoch=0, dataloader_position=0, model=engine.model, optimizer=engine.optimizer)
    path = tmp_path / "ckpt.pt"
    save_resumable_checkpoint(
        path=path, training_state=ts, global_step=engine.global_step, microbatch_in_cycle=0,
        sampler_position=50, sampler_seed=7, sampler_num_blocks=100,
        config_fingerprint=FINGERPRINT, dataset_identity=DATASET_IDENTITY, integrity_key=KEY, run_id="test-run-fixture",
    )
    import json as _json
    manifest_path = path.with_suffix(".pt.resumable.json")
    data = _json.loads(manifest_path.read_text())
    data["global_step"] = 999999
    manifest_path.write_text(_json.dumps(data))
    with pytest.raises(ResumableManifestTamperedError):
        restore_resumable_checkpoint(
            path=path, expected_config_fingerprint=FINGERPRINT, expected_dataset_identity=DATASET_IDENTITY,
            expected_sampler_seed=7, expected_sampler_num_blocks=100, integrity_key=KEY, run_id="test-run-fixture",
        )


def test_p0_04_tampered_sampler_position_and_microbatch_are_rejected(tmp_path):
    engine, batch = _build_engine_and_run_steps(1)
    ts = TrainingState.capture(step=engine.global_step, epoch=0, dataloader_position=0, model=engine.model, optimizer=engine.optimizer)
    path = tmp_path / "ckpt.pt"
    save_resumable_checkpoint(
        path=path, training_state=ts, global_step=engine.global_step, microbatch_in_cycle=0,
        sampler_position=50, sampler_seed=7, sampler_num_blocks=100,
        config_fingerprint=FINGERPRINT, dataset_identity=DATASET_IDENTITY, integrity_key=KEY, run_id="test-run-fixture",
    )
    import json as _json
    manifest_path = path.with_suffix(".pt.resumable.json")
    data = _json.loads(manifest_path.read_text())
    data["sampler_position"] = 888888
    data["microbatch_in_cycle"] = 5
    manifest_path.write_text(_json.dumps(data))
    with pytest.raises(ResumableManifestTamperedError):
        restore_resumable_checkpoint(
            path=path, expected_config_fingerprint=FINGERPRINT, expected_dataset_identity=DATASET_IDENTITY,
            expected_sampler_seed=7, expected_sampler_num_blocks=100, integrity_key=KEY, run_id="test-run-fixture",
        )


def test_p0_04_wrong_integrity_key_is_rejected(tmp_path):
    engine, batch = _build_engine_and_run_steps(1)
    ts = TrainingState.capture(step=engine.global_step, epoch=0, dataloader_position=0, model=engine.model, optimizer=engine.optimizer)
    path = tmp_path / "ckpt.pt"
    save_resumable_checkpoint(
        path=path, training_state=ts, global_step=engine.global_step, microbatch_in_cycle=0,
        sampler_position=0, sampler_seed=7, sampler_num_blocks=500,
        config_fingerprint=FINGERPRINT, dataset_identity=DATASET_IDENTITY, integrity_key=KEY, run_id="test-run-fixture",
    )
    with pytest.raises(ResumableManifestTamperedError):
        restore_resumable_checkpoint(
            path=path, expected_config_fingerprint=FINGERPRINT, expected_dataset_identity=DATASET_IDENTITY,
            expected_sampler_seed=7, expected_sampler_num_blocks=500, integrity_key=b"a-completely-different-key-xxxxx", run_id="test-run-fixture",
        )


def test_p0_04_empty_integrity_key_is_rejected_at_save_time():
    with pytest.raises(ValueError):
        save_resumable_checkpoint(
            path="/tmp/unused.pt", training_state=None, global_step=0, microbatch_in_cycle=0,  # type: ignore[arg-type]
            sampler_position=0, sampler_seed=0, sampler_num_blocks=1,
            config_fingerprint="x", dataset_identity=DATASET_IDENTITY, integrity_key=b"", run_id="test-run-fixture",
        )


def test_p0_04_replaying_a_valid_old_checkpoints_manifest_onto_a_newer_checkpoint_is_rejected(tmp_path):
    """Swapping an OLD (but validly-tagged, for a DIFFERENT save) sidecar
    manifest onto a newer checkpoint body must not be silently accepted
    -- the inner_checkpoint_sha256 bound into the HMAC tag will no
    longer match the newer body's real hash."""
    engine, batch = _build_engine_and_run_steps(1)
    ts1 = TrainingState.capture(step=1, epoch=0, dataloader_position=0, model=engine.model, optimizer=engine.optimizer)
    path1 = tmp_path / "ckpt1.pt"
    save_resumable_checkpoint(
        path=path1, training_state=ts1, global_step=1, microbatch_in_cycle=0,
        sampler_position=0, sampler_seed=7, sampler_num_blocks=500,
        config_fingerprint=FINGERPRINT, dataset_identity=DATASET_IDENTITY, integrity_key=KEY, run_id="test-run-fixture",
    )
    engine.step(batch, batch.clone(), capability=TEST_CAP)
    ts2 = TrainingState.capture(step=2, epoch=0, dataloader_position=0, model=engine.model, optimizer=engine.optimizer)
    path2 = tmp_path / "ckpt2.pt"
    save_resumable_checkpoint(
        path=path2, training_state=ts2, global_step=2, microbatch_in_cycle=0,
        sampler_position=0, sampler_seed=7, sampler_num_blocks=500,
        config_fingerprint=FINGERPRINT, dataset_identity=DATASET_IDENTITY, integrity_key=KEY, run_id="test-run-fixture",
    )
    # Replay: copy checkpoint 1's manifest onto checkpoint 2's body.
    manifest1_path = path1.with_suffix(".pt.resumable.json")
    manifest2_path = path2.with_suffix(".pt.resumable.json")
    manifest2_path.write_text(manifest1_path.read_text())
    with pytest.raises((ResumableManifestTamperedError, ChecksumMismatchError)):
        restore_resumable_checkpoint(
            path=path2, expected_config_fingerprint=FINGERPRINT, expected_dataset_identity=DATASET_IDENTITY,
            expected_sampler_seed=7, expected_sampler_num_blocks=500, integrity_key=KEY, run_id="test-run-fixture",
        )


def test_p0_04_concurrent_access_still_produces_a_self_consistent_checkpoint(tmp_path):
    """Two sequential (not literally concurrent in-process, but
    exercising the same exclusive-lock discipline) saves to the SAME
    path must never leave a checkpoint body and manifest from different
    saves paired together."""
    engine, batch = _build_engine_and_run_steps(0)
    path = tmp_path / "ckpt.pt"
    for step in range(1, 4):
        ts = TrainingState.capture(step=step, epoch=0, dataloader_position=0, model=engine.model, optimizer=engine.optimizer)
        save_resumable_checkpoint(
            path=path, training_state=ts, global_step=step, microbatch_in_cycle=0,
            sampler_position=step, sampler_seed=7, sampler_num_blocks=500,
            config_fingerprint=FINGERPRINT, dataset_identity=DATASET_IDENTITY, integrity_key=KEY, run_id="test-run-fixture",
        )
        restored = restore_resumable_checkpoint(
            path=path, expected_config_fingerprint=FINGERPRINT, expected_dataset_identity=DATASET_IDENTITY,
            expected_sampler_seed=7, expected_sampler_num_blocks=500, integrity_key=KEY, run_id="test-run-fixture",
        )
        assert restored.global_step == step
        assert restored.sampler_position == step


# ==============================================================================
# AUDIT #075 (successor requalification) -- anti-rollback ledger & weak-key custody.
# ==============================================================================

def test_audit075_weak_integrity_key_is_rejected_at_save_time(tmp_path):
    from orca.genesis.training.resumable_checkpoint import WeakIntegrityKeyError

    engine, batch = _build_engine_and_run_steps(0)
    ts = TrainingState.capture(step=engine.global_step, epoch=0, dataloader_position=0, model=engine.model, optimizer=engine.optimizer)
    path = tmp_path / "ckpt.pt"
    with pytest.raises(WeakIntegrityKeyError):
        save_resumable_checkpoint(
            path=path, training_state=ts, global_step=engine.global_step, microbatch_in_cycle=0,
            sampler_position=0, sampler_seed=7, sampler_num_blocks=500,
            config_fingerprint=FINGERPRINT, dataset_identity=DATASET_IDENTITY, integrity_key=b"short-key", run_id="weak-key-run",
        )
    assert not path.exists()


def test_audit075_rollback_to_an_older_checkpoint_is_rejected(tmp_path):
    """Mission D: once the run's ledger has recorded a higher step,
    restoring an OLDER, validly-signed checkpoint (even one that passes
    every other check) must be rejected -- the exact scenario the
    Audit #075 adversarial suite's own
    test_p0_04_rollback_vulnerability_demonstration showed was
    previously accepted unconditionally."""
    from orca.genesis.training.resumable_checkpoint import CheckpointRollbackError

    engine, batch = _build_engine_and_run_steps(0)
    run_id = "rollback-detection-run"

    ts5 = TrainingState.capture(step=5, epoch=0, dataloader_position=0, model=engine.model, optimizer=engine.optimizer)
    path5 = tmp_path / "ckpt_step5.pt"
    save_resumable_checkpoint(
        path=path5, training_state=ts5, global_step=5, microbatch_in_cycle=0,
        sampler_position=5, sampler_seed=7, sampler_num_blocks=500,
        config_fingerprint=FINGERPRINT, dataset_identity=DATASET_IDENTITY, integrity_key=KEY, run_id=run_id,
    )

    # The run progresses further and checkpoints again at step 100 --
    # this is what advances the ledger's high-water mark past 5.
    ts100 = TrainingState.capture(step=100, epoch=0, dataloader_position=0, model=engine.model, optimizer=engine.optimizer)
    path100 = tmp_path / "ckpt_step100.pt"
    save_resumable_checkpoint(
        path=path100, training_state=ts100, global_step=100, microbatch_in_cycle=0,
        sampler_position=100, sampler_seed=7, sampler_num_blocks=500,
        config_fingerprint=FINGERPRINT, dataset_identity=DATASET_IDENTITY, integrity_key=KEY, run_id=run_id,
    )

    # An attacker (or an operator error) now tries to restore the OLDER,
    # still perfectly validly-signed step-5 checkpoint under the SAME run_id.
    with pytest.raises(CheckpointRollbackError):
        restore_resumable_checkpoint(
            path=path5, expected_config_fingerprint=FINGERPRINT, expected_dataset_identity=DATASET_IDENTITY,
            expected_sampler_seed=7, expected_sampler_num_blocks=500, integrity_key=KEY, run_id=run_id,
        )

    # The newer checkpoint remains restorable.
    restored = restore_resumable_checkpoint(
        path=path100, expected_config_fingerprint=FINGERPRINT, expected_dataset_identity=DATASET_IDENTITY,
        expected_sampler_seed=7, expected_sampler_num_blocks=500, integrity_key=KEY, run_id=run_id,
    )
    assert restored.global_step == 100


def test_audit075_a_different_run_id_has_its_own_independent_ledger(tmp_path):
    """Two DIFFERENT logical runs (different run_id) must never share
    or interfere with each other's rollback ledger, even if their
    checkpoints happen to live in the same directory."""
    engine, batch = _build_engine_and_run_steps(0)

    ts_a = TrainingState.capture(step=50, epoch=0, dataloader_position=0, model=engine.model, optimizer=engine.optimizer)
    path_a = tmp_path / "run_a.pt"
    save_resumable_checkpoint(
        path=path_a, training_state=ts_a, global_step=50, microbatch_in_cycle=0,
        sampler_position=0, sampler_seed=7, sampler_num_blocks=500,
        config_fingerprint=FINGERPRINT, dataset_identity=DATASET_IDENTITY, integrity_key=KEY, run_id="run-a",
    )

    ts_b = TrainingState.capture(step=1, epoch=0, dataloader_position=0, model=engine.model, optimizer=engine.optimizer)
    path_b = tmp_path / "run_b.pt"
    save_resumable_checkpoint(
        path=path_b, training_state=ts_b, global_step=1, microbatch_in_cycle=0,
        sampler_position=0, sampler_seed=7, sampler_num_blocks=500,
        config_fingerprint=FINGERPRINT, dataset_identity=DATASET_IDENTITY, integrity_key=KEY, run_id="run-b",
    )
    restored_b = restore_resumable_checkpoint(
        path=path_b, expected_config_fingerprint=FINGERPRINT, expected_dataset_identity=DATASET_IDENTITY,
        expected_sampler_seed=7, expected_sampler_num_blocks=500, integrity_key=KEY, run_id="run-b",
    )
    assert restored_b.global_step == 1  # run-b's low step is NOT rejected because of run-a's unrelated, higher one


def test_audit075_tampered_ledger_file_is_rejected(tmp_path):
    """The ledger itself is HMAC-protected -- directly editing its
    recorded highest_global_step must be caught, never silently trusted."""
    import json as _json

    from orca.genesis.training.resumable_checkpoint import _ledger_path

    engine, batch = _build_engine_and_run_steps(0)
    run_id = "tamper-ledger-run"
    ts = TrainingState.capture(step=10, epoch=0, dataloader_position=0, model=engine.model, optimizer=engine.optimizer)
    path = tmp_path / "ckpt.pt"
    save_resumable_checkpoint(
        path=path, training_state=ts, global_step=10, microbatch_in_cycle=0,
        sampler_position=0, sampler_seed=7, sampler_num_blocks=500,
        config_fingerprint=FINGERPRINT, dataset_identity=DATASET_IDENTITY, integrity_key=KEY, run_id=run_id,
    )

    ledger_file = _ledger_path(run_id)
    data = _json.loads(ledger_file.read_text())
    data["highest_global_step"] = 0  # attacker lowers the watermark to erase evidence of rollback
    ledger_file.write_text(_json.dumps(data))

    with pytest.raises(ResumableManifestTamperedError):
        restore_resumable_checkpoint(
            path=path, expected_config_fingerprint=FINGERPRINT, expected_dataset_identity=DATASET_IDENTITY,
            expected_sampler_seed=7, expected_sampler_num_blocks=500, integrity_key=KEY, run_id=run_id,
        )


def test_audit075_simultaneous_old_checkpoint_and_old_ledger_replay_is_not_detected(tmp_path):
    """CTO pre-handoff security directive: challenges whether rollback
    prevention has an independent trusted monotonic anchor. It does
    not -- this test independently reproduces, and documents as a
    KNOWN, UNRESOLVED gap (not silently patched), the exact attack:
    an attacker who saved a copy of this run's ledger file from an
    earlier, legitimate point can replace BOTH the current checkpoint
    (+ manifest) AND the current ledger with an older, mutually
    consistent, still-validly-HMAC'd pair -- with no knowledge of
    integrity_key required, since the replayed ledger's HMAC was
    genuinely computed by this same process at save time. This is
    exactly why resumable_checkpoint.py's own docstring, "Rollback
    protection", now states plainly that this ledger is NOT an
    independently anchored anti-rollback authority."""
    from orca.genesis.training.resumable_checkpoint import _ledger_path

    engine, batch = _build_engine_and_run_steps(0)
    run_id = "simultaneous-replay-run"

    ts5 = TrainingState.capture(step=5, epoch=0, dataloader_position=0, model=engine.model, optimizer=engine.optimizer)
    path5 = tmp_path / "ckpt_step5.pt"
    save_resumable_checkpoint(
        path=path5, training_state=ts5, global_step=5, microbatch_in_cycle=0,
        sampler_position=5, sampler_seed=7, sampler_num_blocks=500,
        config_fingerprint=FINGERPRINT, dataset_identity=DATASET_IDENTITY, integrity_key=KEY, run_id=run_id,
    )
    manifest5_path = path5.with_suffix(".pt.resumable.json")
    manifest5_snapshot = manifest5_path.read_text()
    ledger_path = _ledger_path(run_id)
    ledger_snapshot_at_step5 = ledger_path.read_text()  # the attacker's saved copy, still validly HMAC'd

    # The run progresses further -- step 100 -- advancing both the
    # checkpoint and the ledger's high-water mark.
    ts100 = TrainingState.capture(step=100, epoch=0, dataloader_position=0, model=engine.model, optimizer=engine.optimizer)
    path100 = tmp_path / "ckpt_step100.pt"
    save_resumable_checkpoint(
        path=path100, training_state=ts100, global_step=100, microbatch_in_cycle=0,
        sampler_position=100, sampler_seed=7, sampler_num_blocks=500,
        config_fingerprint=FINGERPRINT, dataset_identity=DATASET_IDENTITY, integrity_key=KEY, run_id=run_id,
    )

    # Attacker (or a restored backup) now replaces the CURRENT ledger
    # with the saved, OLD, still-validly-signed step-5 snapshot --
    # requires filesystem write access only, never integrity_key.
    ledger_path.write_text(ledger_snapshot_at_step5)
    assert manifest5_path.read_text() == manifest5_snapshot  # path5's own files were never touched -- still the original, valid step-5 pair

    # The rollback to step 5 is now accepted -- NOT detected, because
    # the ledger the restore checks against was ALSO rolled back,
    # consistently, to match.
    restored = restore_resumable_checkpoint(
        path=path5, expected_config_fingerprint=FINGERPRINT, expected_dataset_identity=DATASET_IDENTITY,
        expected_sampler_seed=7, expected_sampler_num_blocks=500, integrity_key=KEY, run_id=run_id,
    )
    assert restored.global_step == 5, (
        "if this assertion ever fails, the anti-rollback ledger has been independently anchored since this "
        "test was written -- update resumable_checkpoint.py's own 'Rollback protection' docstring accordingly"
    )
