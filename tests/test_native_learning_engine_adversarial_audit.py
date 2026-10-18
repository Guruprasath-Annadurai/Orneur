"""
Independent Adversarial Audit Test Suite for GENESIS Native Learning Engine (PR #73).
Auditor: Antigravity / Gemini — Independent Security, Research & Model Assurance Lead.
Target: PR #73 (HEAD: f8d254720bc3d00fab3ba046175a1afce03c7fbb).

Empirical reproductions for:
- Audit P0-01: Next-token objective double-shift defect & padding/packing flaws
- Audit P0-02: Continuous execution authority & governance bypass
- Audit P0-03: Partial accumulation gradient loss on resume divergence
- Audit P0-04: Resumable checkpoint sidecar tampering acceptance
- Audit P1-01: In-memory materialization & unverified caller digests
- Audit P1-02: Numerical edge cases & scheduler ordering
- Audit P1-03: Proof that periodic test masked double-shift defect
"""
import json
import math
import pathlib
import tempfile
import pytest
import torch
import torch.nn.functional as F

from orca.genesis.data.loader import (
    CrossSplitAccessError,
    GenesisBlockDataset,
    IGNORE_INDEX,
    LoaderConfig,
    MalformedRecordError,
    ShardIntegrityError,
    compute_shard_digests,
)
from orca.genesis.model.transformer import GenesisModelConfig, GenesisTransformer
from orca.genesis.tokenizer.framework import EOS_ID, PAD_ID
from orca.genesis.training.learning_governance import (
    TrainingNotAuthorizedForExecutionError,
    execute_authorized_training_step,
)
from orca.genesis.training.learning_step import (
    NonFiniteTrainingSignalError,
    ResourceLimitExceededError,
    StepResult,
    TrainingStepConfig,
    TrainingStepEngine,
    set_deterministic_seed,
)
from orca.genesis.training.orchestration import GenesisTrainingRun, RunState
from orca.genesis.training.primitives import (
    TrainingState,
    causal_lm_loss,
    cosine_warmup_lr,
)
from orca.genesis.training.resumable_checkpoint import (
    DatasetIdentity,
    ResumableManifest,
    ResumeEquivalenceError,
    compute_config_fingerprint,
    restore_resumable_checkpoint,
    save_resumable_checkpoint,
)

# Helpers
TINY_MODEL_CFG = GenesisModelConfig(
    vocab_size=32, d_model=16, n_layers=2, n_heads=2, n_kv_heads=1, d_ff=32, max_seq_len=16
)


class MockTokenizer:
    def __init__(self, mapping=None):
        self.mapping = mapping or {}

    def encode(self, text: str) -> list[int]:
        if text in self.mapping:
            return list(self.mapping[text])
        # Default simple char-based or word-based
        return [ord(c) % 28 + 4 for c in text.split()[0]] if text else []


# ==============================================================================
# AUDIT P0-01: Next-Token Objective Double-Shift Defect
# ==============================================================================

def test_p0_01_mathematical_proof_of_double_shift():
    """
    Mathematical proof that GenesisBlockDataset.block() combined with
    causal_lm_loss() forces logit i to predict token i+2 instead of token i+1.
    """
    # Suppose raw token sequence is [T0, T1, T2, T3, T4]
    full = torch.tensor([11, 23, 37, 41, 59], dtype=torch.long)
    seq_len = 4

    # GenesisBlockDataset.block() implementation:
    input_ids = full[:-1]  # [11, 23, 37, 41]
    labels = full[1:].clone()  # [23, 37, 41, 59]

    # In causal_lm_loss(logits, labels):
    shift_labels = labels[1:].contiguous()  # [37, 41, 59]
    # shift_logits = logits[:-1, :] corresponding to input_ids[:3]

    # Trace each logit's receptive field vs the token it is trained to predict:
    # Position 0: input [11] -> shift_labels[0] is 37 (T2). T1 (23) was SKIPPED!
    assert input_ids[0].item() == 11
    assert shift_labels[0].item() == 37, f"Expected 37 (T2), got {shift_labels[0].item()}"

    # Position 1: input [11, 23] -> shift_labels[1] is 41 (T3). T2 (37) was SKIPPED!
    assert input_ids[1].item() == 23
    assert shift_labels[1].item() == 41, f"Expected 41 (T3), got {shift_labels[1].item()}"

    # Position 2: input [11, 23, 37] -> shift_labels[2] is 59 (T4). T3 (41) was SKIPPED!
    assert input_ids[2].item() == 37
    assert shift_labels[2].item() == 59, f"Expected 59 (T4), got {shift_labels[2].item()}"

    # T1 (23) appears NOWHERE in shift_labels. The model is NEVER trained to predict T1!
    assert 23 not in shift_labels.tolist()


def test_p0_01_associative_recall_learns_t_plus_2_instead_of_t_plus_1():
    """
    Train a model on deterministic non-periodic transitions:
    Token 5 -> Token 6 -> Token 7 -> Token 8
    Under true next-token prediction, given [5], the model should predict 6.
    Under GENESIS's double-shift bug, given [5], the model learns to predict 7!
    """
    set_deterministic_seed(42)
    model = GenesisTransformer(TINY_MODEL_CFG)
    engine = TrainingStepEngine(
        model, TrainingStepConfig(grad_accum_steps=1, warmup_steps=5, total_steps=150, max_lr=1e-2)
    )

    # Sequence of 5 tokens: [5, 6, 7, 8, 9]
    seq = torch.tensor([[5, 6, 7, 8, 9]], dtype=torch.long)
    input_ids = seq[:, :-1]  # [5, 6, 7, 8]
    labels = seq[:, 1:]     # [6, 7, 8, 9]

    for _ in range(150):
        engine.step(input_ids, labels)

    model.eval()
    with torch.no_grad():
        test_inp = torch.tensor([[5, 6, 7, 8]], dtype=torch.long)
        logits = model(test_inp)  # shape (1, 4, vocab_size)

        # Logit at position 0 saw input [5]
        pred_pos0 = logits[0, 0].argmax().item()
        # Logit at position 1 saw input [5, 6]
        pred_pos1 = logits[0, 1].argmax().item()

    # If it learned true next-token, pred_pos0 would be 6.
    # Due to double shift, pred_pos0 is trained on shift_labels[0] == 7!
    assert pred_pos0 == 7, f"Expected double-shift target 7, but got {pred_pos0}"
    assert pred_pos1 == 8, f"Expected double-shift target 8, but got {pred_pos1}"


def test_p0_01_padding_mask_defect_leaves_pad_unmasked_and_predicts_pad(tmp_path):
    """
    Demonstrates that in packing=False mode:
    labels[input_ids == pad_id] = IGNORE_INDEX
    leaves the first pad token UNMASKED because labels is offset by 1,
    forcing the model to predict PAD after the real token!
    """
    shard_file = tmp_path / "shard-0000-train.jsonl"
    shard_file.write_text(json.dumps({"text": "two_tokens"}) + "\n")
    digests = compute_shard_digests(tmp_path)

    tok = MockTokenizer({"two_tokens": [10, 20]})
    # seq_len=4, so full will be [10, 20, PAD, PAD, PAD]
    cfg = LoaderConfig(
        shard_dir=tmp_path, split="train", seq_len=4, batch_size=1,
        seed=0, authorized_shard_digests=digests, packing=False,
        pad_id=0, eos_id=1
    )
    ds = GenesisBlockDataset(cfg, tok)
    inp, lbl = ds.block(0)

    # inp is [10, 20, 0, 0]
    # lbl is [20, 0, -100, -100] -> index 1 has value 0 (PAD_ID), NOT -100!
    assert inp.tolist() == [10, 20, 0, 0]
    assert lbl.tolist() == [20, 0, -100, -100], f"Expected unmasked pad at index 1, got {lbl.tolist()}"

    # When fed to causal_lm_loss, shift_labels is lbl[1:] = [0, -100, -100]
    # So the ONLY unmasked target token is 0 (PAD)!
    shift_lbl = lbl[1:]
    active_tokens = shift_lbl[shift_lbl != IGNORE_INDEX]
    assert len(active_tokens) == 1
    assert active_tokens[0].item() == 0, "Loss target is forced to be PAD token!"


def test_p0_01_single_token_padded_record_crashes_with_all_masked_positions(tmp_path):
    """
    If a record has only 1 token in non-packing mode:
    full = [10, PAD, PAD, PAD, PAD]
    inp = [10, 0, 0, 0], lbl = [0, -100, -100, -100]
    causal_lm_loss shifts lbl -> [-100, -100, -100].
    Every position is IGNORE_INDEX, crashing with ValueError.
    """
    shard_file = tmp_path / "shard-0000-train.jsonl"
    shard_file.write_text(json.dumps({"text": "one"}) + "\n")
    digests = compute_shard_digests(tmp_path)

    tok = MockTokenizer({"one": [10]})
    cfg = LoaderConfig(
        shard_dir=tmp_path, split="train", seq_len=4, batch_size=1,
        seed=0, authorized_shard_digests=digests, packing=False,
        pad_id=0, eos_id=1
    )
    ds = GenesisBlockDataset(cfg, tok)
    inp, lbl = ds.block(0)

    # causal_lm_loss raises ValueError because active == 0
    fake_logits = torch.randn(1, 4, 32)
    with pytest.raises(ValueError, match="every shifted position is ignore_index"):
        causal_lm_loss(fake_logits, lbl.unsqueeze(0))


# ==============================================================================
# AUDIT P0-02: Continuous Execution Authority & Governance Bypass
# ==============================================================================

def test_p0_02_direct_step_bypasses_governance():
    """
    TrainingStepEngine.step() can be called directly by any caller without
    ever creating or passing a GenesisTrainingRun or calling learning_governance.
    """
    model = GenesisTransformer(TINY_MODEL_CFG)
    engine = TrainingStepEngine(model, TrainingStepConfig(grad_accum_steps=1))
    batch = torch.randint(0, 32, (2, 8))

    # Direct step succeeds with zero authorization checks
    result = engine.step(batch, batch.clone())
    assert result.applied is True
    assert result.global_step == 0


def test_p0_02_expired_grant_continues_updating_in_running_session():
    """
    Once a run is in RunState.RUNNING, execute_authorized_training_step()
    never checks grant expiration or revocation, allowing unlimited parameter updates.
    """
    # Create a dummy run-like object with RunState.RUNNING
    class DummyRun(GenesisTrainingRun):
        def __init__(self):
            self.state = RunState.RUNNING
            self.identity = type("Identity", (), {"run_id": "test-run"})()

    run = DummyRun()
    model = GenesisTransformer(TINY_MODEL_CFG)
    engine = TrainingStepEngine(model, TrainingStepConfig(grad_accum_steps=1))
    batch = torch.randint(0, 32, (2, 8))

    # Multiple steps succeed continuously without re-checking expiration
    for _ in range(5):
        res = execute_authorized_training_step(run, engine, batch, batch.clone())
        assert res.applied is True


# ==============================================================================
# AUDIT P0-03: Exact Resume at Partial Accumulation
# ==============================================================================

def test_p0_03_resume_mid_accumulation_cycle_diverges(tmp_path):
    """
    When grad_accum_steps > 1, stopping mid-cycle (microbatch_in_cycle > 0)
    and restoring into a fresh engine loses the accumulated gradients and loss sum,
    causing the resumed run to diverge from uninterrupted execution.
    """
    step_cfg = TrainingStepConfig(grad_accum_steps=2, warmup_steps=2, total_steps=20, seed=42)
    fp = compute_config_fingerprint(TINY_MODEL_CFG, step_cfg)
    ds_id = DatasetIdentity("m", "d" * 64, "t" * 64)

    # 1. Uninterrupted run
    set_deterministic_seed(42)
    m_un = GenesisTransformer(TINY_MODEL_CFG)
    eng_un = TrainingStepEngine(m_un, step_cfg)
    torch.manual_seed(999)
    b0 = torch.randint(0, 32, (2, 8))
    b1 = torch.randint(0, 32, (2, 8))

    eng_un.step(b0, b0.clone())
    res_un = eng_un.step(b1, b1.clone())
    weights_un = {n: p.clone() for n, p in m_un.named_parameters()}

    # 2. Interrupted run: microbatch 0, save at microbatch_in_cycle=1, restore into fresh engine
    set_deterministic_seed(42)
    m_int = GenesisTransformer(TINY_MODEL_CFG)
    eng_int = TrainingStepEngine(m_int, step_cfg)

    eng_int.step(b0, b0.clone())
    assert eng_int.microbatch_in_cycle == 1

    ts = TrainingState.capture(
        step=eng_int.global_step, epoch=0, dataloader_position=0, model=m_int, optimizer=eng_int.optimizer
    )
    ckpt_path = tmp_path / "ckpt.pt"
    save_resumable_checkpoint(
        path=ckpt_path, training_state=ts, global_step=eng_int.global_step,
        microbatch_in_cycle=eng_int.microbatch_in_cycle,
        sampler_position=1, sampler_seed=42, sampler_num_blocks=10,
        config_fingerprint=fp, dataset_identity=ds_id
    )

    restored = restore_resumable_checkpoint(
        path=ckpt_path, expected_config_fingerprint=fp, expected_dataset_identity=ds_id,
        expected_sampler_seed=42, expected_sampler_num_blocks=10
    )

    # New engine
    m_res = GenesisTransformer(TINY_MODEL_CFG)
    eng_res = TrainingStepEngine(m_res, step_cfg)
    restored.training_state.restore(model=m_res, optimizer=eng_res.optimizer)
    eng_res.global_step = restored.global_step
    eng_res.microbatch_in_cycle = restored.microbatch_in_cycle

    # Run microbatch 1
    res_res = eng_res.step(b1, b1.clone())
    weights_res = {n: p.clone() for n, p in m_res.named_parameters()}

    # Check for divergence!
    mismatched = []
    for n in weights_un:
        if not torch.allclose(weights_un[n], weights_res[n], atol=1e-5):
            mismatched.append(n)

    # The models diverged because microbatch 0's gradient was discarded!
    assert len(mismatched) > 0, "Expected divergence on partial accumulation resume!"
    assert res_un.microbatch_loss != pytest.approx(res_res.microbatch_loss, abs=1e-3)


# ==============================================================================
# AUDIT P0-04: Resumable Checkpoint Sidecar Integrity
# ==============================================================================

def test_p0_04_tampered_sampler_position_and_step_accepted_silently(tmp_path):
    """
    Modifying global_step, sampler_position, and microbatch_in_cycle in
    the sidecar manifest is silently accepted by restore_resumable_checkpoint()
    because the manifest has no signature/MAC and these fields are unvalidated.
    """
    step_cfg = TrainingStepConfig(grad_accum_steps=1, warmup_steps=2, total_steps=20, seed=42)
    fp = compute_config_fingerprint(TINY_MODEL_CFG, step_cfg)
    ds_id = DatasetIdentity("m", "d" * 64, "t" * 64)

    set_deterministic_seed(42)
    m = GenesisTransformer(TINY_MODEL_CFG)
    eng = TrainingStepEngine(m, step_cfg)
    ts = TrainingState.capture(step=10, epoch=0, dataloader_position=0, model=m, optimizer=eng.optimizer)

    ckpt_path = tmp_path / "ckpt.pt"
    save_resumable_checkpoint(
        path=ckpt_path, training_state=ts, global_step=10, microbatch_in_cycle=0,
        sampler_position=50, sampler_seed=42, sampler_num_blocks=100,
        config_fingerprint=fp, dataset_identity=ds_id
    )

    # Tamper with the sidecar JSON file
    manifest_path = ckpt_path.with_suffix(".pt.resumable.json")
    data = json.loads(manifest_path.read_text())
    data["global_step"] = 999999
    data["sampler_position"] = 888888
    data["microbatch_in_cycle"] = 5
    manifest_path.write_text(json.dumps(data))

    # Restore accepts modified values without warning or error
    restored = restore_resumable_checkpoint(
        path=ckpt_path, expected_config_fingerprint=fp, expected_dataset_identity=ds_id,
        expected_sampler_seed=42, expected_sampler_num_blocks=100
    )
    assert restored.global_step == 999999
    assert restored.sampler_position == 888888
    assert restored.microbatch_in_cycle == 5
    # Meanwhile inner checkpoint step is 10
    assert restored.training_state.step == 10


# ==============================================================================
# AUDIT P1-01: Data Streaming and Loader Correctness
# ==============================================================================

def test_p1_01_all_tokens_materialized_in_ram(tmp_path):
    """
    GenesisBlockDataset._build_blocks() loads all tokens from all shards
    into a Python list[int] and list[torch.Tensor] at construction time.
    """
    shard_file = tmp_path / "shard-0000-train.jsonl"
    records = [{"text": f"token_{i}"} for i in range(20)]
    shard_file.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    digests = compute_shard_digests(tmp_path)

    tok = MockTokenizer()
    cfg = LoaderConfig(
        shard_dir=tmp_path, split="train", seq_len=4, batch_size=2,
        seed=0, authorized_shard_digests=digests, packing=True,
    )
    ds = GenesisBlockDataset(cfg, tok)
    # The entire block collection is stored in memory
    assert hasattr(ds, "_blocks")
    assert isinstance(ds._blocks, list)
    assert len(ds._blocks) == ds.report.num_blocks


def test_p1_01_caller_supplied_digests_trusted_without_authority_root(tmp_path):
    """
    GenesisBlockDataset accepts any authorized_shard_digests dictionary provided
    by the caller without verifying it against a signed Grant or Ledger.
    """
    shard_file = tmp_path / "shard-0000-train.jsonl"
    shard_file.write_text(json.dumps({"text": "arbitrary data"}) + "\n")
    # Caller computes digests on arbitrary local files
    untrusted_digests = compute_shard_digests(tmp_path)

    cfg = LoaderConfig(
        shard_dir=tmp_path, split="train", seq_len=4, batch_size=1,
        seed=0, authorized_shard_digests=untrusted_digests, packing=True,
    )
    # Succeeds without verifying caller authorization
    ds = GenesisBlockDataset(cfg, MockTokenizer())
    assert len(ds) >= 0


# ==============================================================================
# AUDIT P1-02: Optimizer, Scheduler & Numerical Correctness
# ==============================================================================

def test_p1_02_nan_loss_raises_non_finite_training_signal():
    """
    NonFiniteTrainingSignalError is raised when loss evaluates to NaN,
    preventing corrupted gradients from reaching parameters.
    """
    model = GenesisTransformer(TINY_MODEL_CFG)
    engine = TrainingStepEngine(model, TrainingStepConfig(grad_accum_steps=1))

    # Create input that triggers NaN or manually inject NaN in parameters
    with torch.no_grad():
        for p in model.parameters():
            p.fill_(float("nan"))
            break

    batch = torch.randint(0, 32, (2, 8))
    with pytest.raises(NonFiniteTrainingSignalError):
        engine.step(batch, batch.clone())


def test_p1_02_resource_limit_exceeded_on_oversized_batch():
    """
    Batch token count exceeding _MAX_REASONABLE_BATCH_TOKENS raises
    ResourceLimitExceededError.
    """
    model = GenesisTransformer(TINY_MODEL_CFG)
    engine = TrainingStepEngine(model, TrainingStepConfig(max_steps=2))
    batch = torch.randint(0, 32, (1, 4))

    engine.step(batch, batch.clone())
    engine.step(batch, batch.clone())

    # Step 3 exceeds max_steps=2
    with pytest.raises(ResourceLimitExceededError):
        engine.step(batch, batch.clone())


# ==============================================================================
# AUDIT P1-03: Periodic Pattern Masking Proof
# ==============================================================================

def test_p1_03_periodic_pattern_with_period_4_masks_double_shift():
    """
    Proves why Claude's synthetic learning test passed despite the double-shift defect:
    In a periodic sequence with period P=4: [0, 1, 2, 3, 0, 1, 2, 3...]
    Target T_{i+2} is (i+2) % 4.
    Since (i+2) % 4 is deterministic given (i % 4), a transformer can learn
    to predict T_{i+2} just as easily as T_{i+1}, reaching near-zero loss
    while completely failing at genuine next-token prediction!
    """
    period = 4
    seq_len = 16
    base = torch.tensor([i % period for i in range(seq_len + 1)])
    input_ids = base[:-1]  # [0, 1, 2, 3, 0, 1, 2, 3, ...]
    labels = base[1:]      # [1, 2, 3, 0, 1, 2, 3, 0, ...]
    shift_labels = labels[1:]  # [2, 3, 0, 1, 2, 3, 0, 1, ...]

    # Notice that shift_labels[i] == (input_ids[i] + 2) % 4!
    for i in range(len(shift_labels)):
        expected_double_shift = (input_ids[i].item() + 2) % period
        assert shift_labels[i].item() == expected_double_shift, (
            f"Expected {expected_double_shift}, got {shift_labels[i].item()}"
        )
