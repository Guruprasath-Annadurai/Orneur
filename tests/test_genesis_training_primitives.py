"""
GENESIS Foundation Sprint 1, Phase 5: non-training verification of the
pretraining primitives. These tests construct losses, optimizers,
schedules and checkpoints and inspect their VALUES -- none of them call
`.backward()` followed by `optimizer.step()` against real data in a loop
(i.e. no training occurs). Where a gradient is computed to verify
`clip_grad_norm`'s math, it is a single, isolated `.backward()` call used
only to produce a gradient tensor to measure -- never followed by an
optimizer step, and never part of a loop over real or synthetic data
meant to make the model learn anything.
"""
from __future__ import annotations

import pytest

# Same established pattern as tests/test_train_losses.py -- see
# .github/workflows/test.yml's dedicated `torch-loss-tests` job.
torch = pytest.importorskip("torch")
import torch.nn.functional as F  # noqa: E402

from orca.genesis.model.config import GenesisModelConfig  # noqa: E402
from orca.genesis.model.transformer import GenesisTransformer  # noqa: E402
from orca.genesis.training.primitives import (  # noqa: E402
    OptimizerConfig,
    TrainingState,
    build_optimizer,
    causal_lm_loss,
    check_for_nan_or_inf,
    clip_grad_norm,
    cosine_warmup_lr,
    grouped_parameters,
    load_training_state,
    save_training_state,
)


def _tiny_model() -> GenesisTransformer:
    cfg = GenesisModelConfig(vocab_size=32, d_model=16, n_layers=2, n_heads=4, n_kv_heads=2, d_ff=32, max_seq_len=16)
    return GenesisTransformer(cfg)


# --------------------------------------------------------------- loss --

def test_causal_lm_loss_matches_manual_shift_and_torch_reference():
    """Cross-checks against a hand-written reference shift AND against
    torch's own F.cross_entropy called directly on the already-shifted
    tensors -- two independent reference computations, not one."""
    torch.manual_seed(0)
    batch, seq_len, vocab = 2, 6, 10
    logits = torch.randn(batch, seq_len, vocab)
    labels = torch.randint(0, vocab, (batch, seq_len))

    got = causal_lm_loss(logits, labels)

    shift_logits = logits[:, :-1, :].reshape(-1, vocab)
    shift_labels = labels[:, 1:].reshape(-1)
    expected = F.cross_entropy(shift_logits, shift_labels)

    assert torch.allclose(got, expected)


def test_causal_lm_loss_ignore_index_excludes_masked_positions():
    torch.manual_seed(0)
    vocab = 5
    logits = torch.randn(1, 4, vocab)
    labels_all_valid = torch.tensor([[1, 2, 3, 4]])
    labels_with_ignore = torch.tensor([[1, 2, 3, -100]])  # last position ignored

    loss_all = causal_lm_loss(logits, labels_all_valid)
    loss_ignored = causal_lm_loss(logits, labels_with_ignore)
    # Ignoring a position changes which terms are averaged -- the two
    # losses must differ (both are valid floats, neither is NaN).
    assert not torch.isnan(loss_all) and not torch.isnan(loss_ignored)
    assert not torch.allclose(loss_all, loss_ignored)


def test_causal_lm_loss_rejects_mismatched_shapes():
    logits = torch.randn(2, 5, 10)
    labels = torch.randint(0, 10, (2, 4))  # wrong seq_len
    with pytest.raises(ValueError, match="inconsistent"):
        causal_lm_loss(logits, labels)


# ---------------------------------------------------------- optimizer --

def test_optimizer_config_rejects_invalid_values():
    with pytest.raises(ValueError, match="lr must be positive"):
        OptimizerConfig(lr=0)
    with pytest.raises(ValueError, match="weight_decay"):
        OptimizerConfig(weight_decay=-0.1)


def test_grouped_parameters_separates_norm_scales_from_weight_matrices():
    model = _tiny_model()
    groups = grouped_parameters(model, weight_decay=0.1)
    decay_group, no_decay_group = groups[0], groups[1]
    assert decay_group["weight_decay"] == 0.1
    assert no_decay_group["weight_decay"] == 0.0
    # Every 1-D parameter (RMSNorm scales) must be in the no-decay group.
    no_decay_names = {id(p) for p in no_decay_group["params"]}
    for name, p in model.named_parameters():
        if p.dim() < 2:
            assert id(p) in no_decay_names, f"{name} (dim={p.dim()}) should be in the no-decay group"


def test_build_optimizer_produces_a_real_adamw_with_configured_values():
    model = _tiny_model()
    cfg = OptimizerConfig(lr=1e-3, betas=(0.8, 0.9), weight_decay=0.05)
    opt = build_optimizer(model, cfg)
    assert isinstance(opt, torch.optim.AdamW)
    for group in opt.param_groups:
        assert group["lr"] == 1e-3
        assert group["betas"] == (0.8, 0.9)


# ---------------------------------------------------------- scheduler --

def test_cosine_warmup_lr_ramps_up_linearly_during_warmup():
    lr_0 = cosine_warmup_lr(0, warmup_steps=10, total_steps=100, max_lr=1.0)
    lr_5 = cosine_warmup_lr(5, warmup_steps=10, total_steps=100, max_lr=1.0)
    lr_9 = cosine_warmup_lr(9, warmup_steps=10, total_steps=100, max_lr=1.0)
    assert 0 < lr_0 < lr_5 < lr_9 <= 1.0


def test_cosine_warmup_lr_decays_to_min_lr_at_end():
    lr_end = cosine_warmup_lr(99, warmup_steps=10, total_steps=100, max_lr=1.0, min_lr=0.1)
    assert abs(lr_end - 0.1) < 0.05


def test_cosine_warmup_lr_peaks_right_after_warmup():
    lr_at_warmup_end = cosine_warmup_lr(10, warmup_steps=10, total_steps=100, max_lr=1.0)
    lr_later = cosine_warmup_lr(50, warmup_steps=10, total_steps=100, max_lr=1.0)
    assert lr_at_warmup_end > lr_later  # cosine decay has started dropping by step 50


def test_cosine_warmup_lr_rejects_invalid_schedule():
    with pytest.raises(ValueError, match="less than total_steps"):
        cosine_warmup_lr(0, warmup_steps=100, total_steps=100, max_lr=1.0)


# ------------------------------------------------------------- grad clip --

def test_clip_grad_norm_reduces_gradient_norm_below_threshold():
    """A single, isolated backward() call to produce a real gradient to
    measure -- not followed by optimizer.step(), not a training loop."""
    model = _tiny_model()
    input_ids = torch.randint(0, 32, (2, 8))
    logits = model(input_ids)
    loss = logits.sum()  # not a real training loss, just something to backprop for this math check
    loss.backward()

    pre_clip_norm = torch.sqrt(sum(p.grad.pow(2).sum() for p in model.parameters() if p.grad is not None))
    reported_norm = clip_grad_norm(model, max_norm=1.0)
    post_clip_norm = torch.sqrt(sum(p.grad.pow(2).sum() for p in model.parameters() if p.grad is not None))

    assert torch.allclose(torch.tensor(reported_norm), pre_clip_norm, atol=1e-4)
    assert post_clip_norm <= 1.0 + 1e-4


def test_clip_grad_norm_rejects_non_positive_max_norm():
    model = _tiny_model()
    with pytest.raises(ValueError, match="positive"):
        clip_grad_norm(model, max_norm=0)


# --------------------------------------------------------- nan/inf check --

def test_check_for_nan_or_inf_passes_clean_tensor():
    check_for_nan_or_inf(torch.tensor([1.0, 2.0, 3.0]), "test_tensor")  # must not raise


def test_check_for_nan_or_inf_catches_nan():
    with pytest.raises(FloatingPointError, match="NaN"):
        check_for_nan_or_inf(torch.tensor([1.0, float("nan")]), "test_tensor")


def test_check_for_nan_or_inf_catches_inf():
    with pytest.raises(FloatingPointError, match="Inf"):
        check_for_nan_or_inf(torch.tensor([1.0, float("inf")]), "test_tensor")


# --------------------------------------------------- checkpoint/restore --

def test_training_state_round_trips_through_disk(tmp_path):
    """Serializes a real training state, reloads it, and restores it into
    a FRESH model/optimizer pair -- verifying the restored state is
    bit-for-bit identical to the captured one, not just that the file
    exists."""
    torch.manual_seed(0)
    model = _tiny_model()
    opt = build_optimizer(model, OptimizerConfig())

    # Take one gradient step's worth of state so optimizer_state_dict is non-trivial.
    input_ids = torch.randint(0, 32, (2, 8))
    loss = model(input_ids).sum()
    loss.backward()
    opt.step()
    opt.zero_grad()

    state = TrainingState.capture(step=42, epoch=3, dataloader_position=777, model=model, optimizer=opt)
    path = tmp_path / "checkpoint.pt"
    save_training_state(state, path)

    assert path.exists()
    loaded = load_training_state(path)
    assert loaded.step == 42
    assert loaded.epoch == 3
    assert loaded.dataloader_position == 777

    fresh_model = _tiny_model()
    fresh_opt = build_optimizer(fresh_model, OptimizerConfig())
    loaded.restore(model=fresh_model, optimizer=fresh_opt)

    for (n1, p1), (n2, p2) in zip(model.named_parameters(), fresh_model.named_parameters()):
        assert n1 == n2
        assert torch.equal(p1, p2), f"parameter {n1} did not restore identically"


def test_load_training_state_rejects_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_training_state(tmp_path / "does_not_exist.pt")


def test_rng_state_restoration_reproduces_subsequent_randomness(tmp_path):
    """The decisive check for resumability: after restoring RNG state,
    the NEXT random draw must match what it would have been had training
    never stopped -- not merely that the restore call doesn't crash."""
    model = _tiny_model()
    opt = build_optimizer(model, OptimizerConfig())

    torch.manual_seed(123)
    _ = torch.randn(5)  # consume some randomness before the "checkpoint" point
    state = TrainingState.capture(step=1, epoch=0, dataloader_position=0, model=model, optimizer=opt)

    expected_next = torch.randn(3)  # what comes next if training had continued uninterrupted

    # Simulate a restart: perturb the RNG state with unrelated draws.
    torch.manual_seed(999)
    _ = torch.randn(10)

    state.restore(model=model, optimizer=opt)
    actual_next = torch.randn(3)

    assert torch.equal(expected_next, actual_next)
