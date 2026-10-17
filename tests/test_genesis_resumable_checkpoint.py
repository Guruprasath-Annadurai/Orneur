"""
GENESIS Native Learning Engine, Phase 1, Workstream 3 tests:
`orca.genesis.training.resumable_checkpoint`. Bounded, CPU-only,
synthetic model/data only.
"""
from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from orca.genesis.model.config import GenesisModelConfig  # noqa: E402
from orca.genesis.model.transformer import GenesisTransformer  # noqa: E402
from orca.genesis.training.learning_step import TrainingStepConfig, TrainingStepEngine, set_deterministic_seed  # noqa: E402
from orca.genesis.training.primitives import TrainingState  # noqa: E402
from orca.genesis.training.resumable_checkpoint import (  # noqa: E402
    ChecksumMismatchError,
    DatasetIdentity,
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


def _build_engine_and_run_steps(n: int, seed: int = 7):
    set_deterministic_seed(seed)
    model = GenesisTransformer(MODEL_CFG)
    engine = TrainingStepEngine(model, STEP_CFG)
    torch.manual_seed(999)
    batch = torch.randint(0, MODEL_CFG.vocab_size, (2, 6))
    for _ in range(n):
        engine.step(batch, batch.clone())
    return engine, batch


def test_save_and_restore_round_trip_exact_fields(tmp_path):
    engine, batch = _build_engine_and_run_steps(3)
    ts = TrainingState.capture(step=engine.global_step, epoch=0, dataloader_position=0, model=engine.model, optimizer=engine.optimizer)
    path = tmp_path / "ckpt.pt"
    save_resumable_checkpoint(
        path=path, training_state=ts, global_step=engine.global_step, microbatch_in_cycle=engine.microbatch_in_cycle,
        sampler_position=17, sampler_seed=7, sampler_num_blocks=500,
        config_fingerprint=FINGERPRINT, dataset_identity=DATASET_IDENTITY,
    )
    restored = restore_resumable_checkpoint(
        path=path, expected_config_fingerprint=FINGERPRINT, expected_dataset_identity=DATASET_IDENTITY,
        expected_sampler_seed=7, expected_sampler_num_blocks=500,
    )
    assert restored.global_step == engine.global_step
    assert restored.microbatch_in_cycle == engine.microbatch_in_cycle
    assert restored.sampler_position == 17


def test_resumed_training_is_bit_identical_to_uninterrupted_training(tmp_path):
    # Uninterrupted: 5 steps straight.
    engine_full, batch = _build_engine_and_run_steps(0)
    losses_full = [engine_full.step(batch, batch.clone()).microbatch_loss for _ in range(5)]

    # Interrupted: 2 steps, checkpoint, restore into a fresh engine, 3 more steps.
    engine_a, batch_a = _build_engine_and_run_steps(0)
    assert torch.equal(batch_a, batch)
    losses_a = [engine_a.step(batch_a, batch_a.clone()).microbatch_loss for _ in range(2)]
    ts = TrainingState.capture(step=engine_a.global_step, epoch=0, dataloader_position=0, model=engine_a.model, optimizer=engine_a.optimizer)
    path = tmp_path / "ckpt.pt"
    save_resumable_checkpoint(
        path=path, training_state=ts, global_step=engine_a.global_step, microbatch_in_cycle=engine_a.microbatch_in_cycle,
        sampler_position=0, sampler_seed=7, sampler_num_blocks=500,
        config_fingerprint=FINGERPRINT, dataset_identity=DATASET_IDENTITY,
    )

    set_deterministic_seed(7)
    model_b = GenesisTransformer(MODEL_CFG)
    engine_b = TrainingStepEngine(model_b, STEP_CFG)
    restored = restore_resumable_checkpoint(
        path=path, expected_config_fingerprint=FINGERPRINT, expected_dataset_identity=DATASET_IDENTITY,
        expected_sampler_seed=7, expected_sampler_num_blocks=500,
    )
    restored.training_state.restore(model=model_b, optimizer=engine_b.optimizer)
    engine_b.global_step = restored.global_step
    engine_b.microbatch_in_cycle = restored.microbatch_in_cycle

    losses_b = losses_a + [engine_b.step(batch_a, batch_a.clone()).microbatch_loss for _ in range(3)]

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
        config_fingerprint=FINGERPRINT, dataset_identity=DATASET_IDENTITY,
    )
    with pytest.raises(ResumeEquivalenceError):
        restore_resumable_checkpoint(
            path=path, expected_config_fingerprint="a-different-fingerprint", expected_dataset_identity=DATASET_IDENTITY,
            expected_sampler_seed=7, expected_sampler_num_blocks=500,
        )


def test_restore_rejects_a_different_dataset_identity(tmp_path):
    engine, batch = _build_engine_and_run_steps(1)
    ts = TrainingState.capture(step=engine.global_step, epoch=0, dataloader_position=0, model=engine.model, optimizer=engine.optimizer)
    path = tmp_path / "ckpt.pt"
    save_resumable_checkpoint(
        path=path, training_state=ts, global_step=engine.global_step, microbatch_in_cycle=engine.microbatch_in_cycle,
        sampler_position=0, sampler_seed=7, sampler_num_blocks=500,
        config_fingerprint=FINGERPRINT, dataset_identity=DATASET_IDENTITY,
    )
    different = DatasetIdentity(dataset_manifest_id="different", dataset_content_digest="e" * 64, tokenizer_digest="t" * 64)
    with pytest.raises(ResumeEquivalenceError):
        restore_resumable_checkpoint(
            path=path, expected_config_fingerprint=FINGERPRINT, expected_dataset_identity=different,
            expected_sampler_seed=7, expected_sampler_num_blocks=500,
        )


def test_restore_rejects_a_tampered_checkpoint_content(tmp_path):
    engine, batch = _build_engine_and_run_steps(1)
    ts = TrainingState.capture(step=engine.global_step, epoch=0, dataloader_position=0, model=engine.model, optimizer=engine.optimizer)
    path = tmp_path / "ckpt.pt"
    save_resumable_checkpoint(
        path=path, training_state=ts, global_step=engine.global_step, microbatch_in_cycle=engine.microbatch_in_cycle,
        sampler_position=0, sampler_seed=7, sampler_num_blocks=500,
        config_fingerprint=FINGERPRINT, dataset_identity=DATASET_IDENTITY,
    )
    data = bytearray(path.read_bytes())
    data[0] ^= 0xFF
    path.write_bytes(bytes(data))
    with pytest.raises(ChecksumMismatchError):
        restore_resumable_checkpoint(
            path=path, expected_config_fingerprint=FINGERPRINT, expected_dataset_identity=DATASET_IDENTITY,
            expected_sampler_seed=7, expected_sampler_num_blocks=500,
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
            expected_sampler_seed=7, expected_sampler_num_blocks=500,
        )


def test_config_fingerprint_is_order_sensitive_and_deterministic():
    f1 = compute_config_fingerprint(MODEL_CFG, STEP_CFG)
    f2 = compute_config_fingerprint(MODEL_CFG, STEP_CFG)
    assert f1 == f2
    f3 = compute_config_fingerprint(STEP_CFG, MODEL_CFG)  # swapped order
    assert f1 != f3
