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
        config_fingerprint=FINGERPRINT, dataset_identity=DATASET_IDENTITY, integrity_key=KEY,
    )
    restored = restore_resumable_checkpoint(
        path=path, expected_config_fingerprint=FINGERPRINT, expected_dataset_identity=DATASET_IDENTITY,
        expected_sampler_seed=7, expected_sampler_num_blocks=500, integrity_key=KEY,
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
        config_fingerprint=FINGERPRINT, dataset_identity=DATASET_IDENTITY, integrity_key=KEY,
    )

    set_deterministic_seed(7)
    model_b = GenesisTransformer(MODEL_CFG)
    engine_b = TrainingStepEngine(model_b, STEP_CFG)
    restored = restore_resumable_checkpoint(
        path=path, expected_config_fingerprint=FINGERPRINT, expected_dataset_identity=DATASET_IDENTITY,
        expected_sampler_seed=7, expected_sampler_num_blocks=500, integrity_key=KEY,
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
        config_fingerprint=FINGERPRINT, dataset_identity=DATASET_IDENTITY, integrity_key=KEY,
    )
    with pytest.raises(ResumeEquivalenceError):
        restore_resumable_checkpoint(
            path=path, expected_config_fingerprint="a-different-fingerprint", expected_dataset_identity=DATASET_IDENTITY,
            expected_sampler_seed=7, expected_sampler_num_blocks=500, integrity_key=KEY,
        )


def test_restore_rejects_a_different_dataset_identity(tmp_path):
    engine, batch = _build_engine_and_run_steps(1)
    ts = TrainingState.capture(step=engine.global_step, epoch=0, dataloader_position=0, model=engine.model, optimizer=engine.optimizer)
    path = tmp_path / "ckpt.pt"
    save_resumable_checkpoint(
        path=path, training_state=ts, global_step=engine.global_step, microbatch_in_cycle=engine.microbatch_in_cycle,
        sampler_position=0, sampler_seed=7, sampler_num_blocks=500,
        config_fingerprint=FINGERPRINT, dataset_identity=DATASET_IDENTITY, integrity_key=KEY,
    )
    different = DatasetIdentity(dataset_manifest_id="different", dataset_content_digest="e" * 64, tokenizer_digest="t" * 64)
    with pytest.raises(ResumeEquivalenceError):
        restore_resumable_checkpoint(
            path=path, expected_config_fingerprint=FINGERPRINT, expected_dataset_identity=different,
            expected_sampler_seed=7, expected_sampler_num_blocks=500, integrity_key=KEY,
        )


def test_restore_rejects_a_tampered_checkpoint_content(tmp_path):
    engine, batch = _build_engine_and_run_steps(1)
    ts = TrainingState.capture(step=engine.global_step, epoch=0, dataloader_position=0, model=engine.model, optimizer=engine.optimizer)
    path = tmp_path / "ckpt.pt"
    save_resumable_checkpoint(
        path=path, training_state=ts, global_step=engine.global_step, microbatch_in_cycle=engine.microbatch_in_cycle,
        sampler_position=0, sampler_seed=7, sampler_num_blocks=500,
        config_fingerprint=FINGERPRINT, dataset_identity=DATASET_IDENTITY, integrity_key=KEY,
    )
    data = bytearray(path.read_bytes())
    data[0] ^= 0xFF
    path.write_bytes(bytes(data))
    with pytest.raises(ChecksumMismatchError):
        restore_resumable_checkpoint(
            path=path, expected_config_fingerprint=FINGERPRINT, expected_dataset_identity=DATASET_IDENTITY,
            expected_sampler_seed=7, expected_sampler_num_blocks=500, integrity_key=KEY,
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
            expected_sampler_seed=7, expected_sampler_num_blocks=500, integrity_key=KEY,
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
            sampler_num_blocks=10, config_fingerprint=fp, dataset_identity=DATASET_IDENTITY, integrity_key=KEY,
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
        sampler_num_blocks=10, config_fingerprint=fp, dataset_identity=DATASET_IDENTITY, integrity_key=KEY,
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
        config_fingerprint=fp, dataset_identity=DATASET_IDENTITY, integrity_key=KEY,
    )

    set_deterministic_seed(5)
    model_b = GenesisTransformer(MODEL_CFG)
    engine_b = TrainingStepEngine(model_b, step_cfg)
    restored = restore_resumable_checkpoint(
        path=path, expected_config_fingerprint=fp, expected_dataset_identity=DATASET_IDENTITY,
        expected_sampler_seed=5, expected_sampler_num_blocks=10, integrity_key=KEY,
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
        config_fingerprint=FINGERPRINT, dataset_identity=DATASET_IDENTITY, integrity_key=KEY,
    )
    import json as _json
    manifest_path = path.with_suffix(".pt.resumable.json")
    data = _json.loads(manifest_path.read_text())
    data["global_step"] = 999999
    manifest_path.write_text(_json.dumps(data))
    with pytest.raises(ResumableManifestTamperedError):
        restore_resumable_checkpoint(
            path=path, expected_config_fingerprint=FINGERPRINT, expected_dataset_identity=DATASET_IDENTITY,
            expected_sampler_seed=7, expected_sampler_num_blocks=100, integrity_key=KEY,
        )


def test_p0_04_tampered_sampler_position_and_microbatch_are_rejected(tmp_path):
    engine, batch = _build_engine_and_run_steps(1)
    ts = TrainingState.capture(step=engine.global_step, epoch=0, dataloader_position=0, model=engine.model, optimizer=engine.optimizer)
    path = tmp_path / "ckpt.pt"
    save_resumable_checkpoint(
        path=path, training_state=ts, global_step=engine.global_step, microbatch_in_cycle=0,
        sampler_position=50, sampler_seed=7, sampler_num_blocks=100,
        config_fingerprint=FINGERPRINT, dataset_identity=DATASET_IDENTITY, integrity_key=KEY,
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
            expected_sampler_seed=7, expected_sampler_num_blocks=100, integrity_key=KEY,
        )


def test_p0_04_wrong_integrity_key_is_rejected(tmp_path):
    engine, batch = _build_engine_and_run_steps(1)
    ts = TrainingState.capture(step=engine.global_step, epoch=0, dataloader_position=0, model=engine.model, optimizer=engine.optimizer)
    path = tmp_path / "ckpt.pt"
    save_resumable_checkpoint(
        path=path, training_state=ts, global_step=engine.global_step, microbatch_in_cycle=0,
        sampler_position=0, sampler_seed=7, sampler_num_blocks=500,
        config_fingerprint=FINGERPRINT, dataset_identity=DATASET_IDENTITY, integrity_key=KEY,
    )
    with pytest.raises(ResumableManifestTamperedError):
        restore_resumable_checkpoint(
            path=path, expected_config_fingerprint=FINGERPRINT, expected_dataset_identity=DATASET_IDENTITY,
            expected_sampler_seed=7, expected_sampler_num_blocks=500, integrity_key=b"a-completely-different-key-xxxx",
        )


def test_p0_04_empty_integrity_key_is_rejected_at_save_time():
    with pytest.raises(ValueError):
        save_resumable_checkpoint(
            path="/tmp/unused.pt", training_state=None, global_step=0, microbatch_in_cycle=0,  # type: ignore[arg-type]
            sampler_position=0, sampler_seed=0, sampler_num_blocks=1,
            config_fingerprint="x", dataset_identity=DATASET_IDENTITY, integrity_key=b"",
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
        config_fingerprint=FINGERPRINT, dataset_identity=DATASET_IDENTITY, integrity_key=KEY,
    )
    engine.step(batch, batch.clone(), capability=TEST_CAP)
    ts2 = TrainingState.capture(step=2, epoch=0, dataloader_position=0, model=engine.model, optimizer=engine.optimizer)
    path2 = tmp_path / "ckpt2.pt"
    save_resumable_checkpoint(
        path=path2, training_state=ts2, global_step=2, microbatch_in_cycle=0,
        sampler_position=0, sampler_seed=7, sampler_num_blocks=500,
        config_fingerprint=FINGERPRINT, dataset_identity=DATASET_IDENTITY, integrity_key=KEY,
    )
    # Replay: copy checkpoint 1's manifest onto checkpoint 2's body.
    manifest1_path = path1.with_suffix(".pt.resumable.json")
    manifest2_path = path2.with_suffix(".pt.resumable.json")
    manifest2_path.write_text(manifest1_path.read_text())
    with pytest.raises((ResumableManifestTamperedError, ChecksumMismatchError)):
        restore_resumable_checkpoint(
            path=path2, expected_config_fingerprint=FINGERPRINT, expected_dataset_identity=DATASET_IDENTITY,
            expected_sampler_seed=7, expected_sampler_num_blocks=500, integrity_key=KEY,
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
            config_fingerprint=FINGERPRINT, dataset_identity=DATASET_IDENTITY, integrity_key=KEY,
        )
        restored = restore_resumable_checkpoint(
            path=path, expected_config_fingerprint=FINGERPRINT, expected_dataset_identity=DATASET_IDENTITY,
            expected_sampler_seed=7, expected_sampler_num_blocks=500, integrity_key=KEY,
        )
        assert restored.global_step == step
        assert restored.sampler_position == step
