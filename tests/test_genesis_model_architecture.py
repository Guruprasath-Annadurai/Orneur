"""
GENESIS Foundation Sprint 1, Phase 5: non-training verification of the
model architecture. Every test here constructs a model, runs forward
passes, and inspects tensors/parameters -- NONE of them call
`.backward()` or `optimizer.step()`. This file performs no gradient-based
training of any kind.
"""
from __future__ import annotations

import pytest

# torch is deliberately NOT installed in the main deterministic CI job
# (same established pattern as tests/test_train_losses.py -- see
# .github/workflows/test.yml's dedicated `torch-loss-tests` job, which
# this file is also run under). `importorskip` produces a legitimate SKIP
# here, not a collection error, when torch is genuinely absent.
torch = pytest.importorskip("torch")

from orca.genesis.model.config import ARCHITECTURE_VERSION, GenesisModelConfig  # noqa: E402
from orca.genesis.model.transformer import (  # noqa: E402
    GenesisTransformer,
    RMSNorm,
    apply_rope,
    precompute_rope_angles,
    repeat_kv,
)


def _tiny_config(**overrides) -> GenesisModelConfig:
    defaults = dict(
        vocab_size=64, d_model=16, n_layers=2, n_heads=4, n_kv_heads=2,
        d_ff=32, max_seq_len=32,
    )
    defaults.update(overrides)
    return GenesisModelConfig(**defaults)


# --------------------------------------------------------------- config --

def test_architecture_version_is_recorded():
    cfg = _tiny_config()
    assert cfg.architecture_version == ARCHITECTURE_VERSION == "genesis-arch-v1"


def test_invalid_config_rejected_not_divisible():
    with pytest.raises(ValueError, match="divisible"):
        GenesisModelConfig(vocab_size=64, d_model=17, n_layers=1, n_heads=4, n_kv_heads=2, d_ff=32, max_seq_len=16)


def test_invalid_config_rejected_kv_heads_exceed_heads():
    with pytest.raises(ValueError, match="cannot exceed"):
        GenesisModelConfig(vocab_size=64, d_model=16, n_layers=1, n_heads=4, n_kv_heads=8, d_ff=32, max_seq_len=16)


def test_invalid_config_rejected_heads_not_multiple_of_kv_heads():
    with pytest.raises(ValueError, match="multiple"):
        GenesisModelConfig(vocab_size=64, d_model=16, n_layers=1, n_heads=4, n_kv_heads=3, d_ff=32, max_seq_len=16)


def test_parameter_count_breakdown_matches_total():
    """Phase 1's exact correction target: the breakdown's own components
    must sum to total_parameters() -- no component can be asserted
    separately from what the real dimensions produce."""
    cfg = _tiny_config()
    b = cfg.breakdown()
    assert cfg.total_parameters() == b["embedding"] + b["all_layers"] + b["final_norm"] + b["lm_head"]


def test_parameter_count_matches_actual_constructed_model():
    """The config's computed total must match the REAL model's real
    parameter count -- not just internal arithmetic self-consistency."""
    cfg = _tiny_config()
    model = GenesisTransformer(cfg)
    assert model.num_parameters(trainable_only=False) == cfg.total_parameters()


def test_tied_embeddings_reduces_parameter_count_as_expected():
    cfg_tied = _tiny_config(tie_embeddings=True)
    cfg_untied = _tiny_config(tie_embeddings=False)
    assert cfg_untied.total_parameters() - cfg_tied.total_parameters() == cfg_tied.vocab_size * cfg_tied.d_model


def test_from_param_budget_rejects_embedding_alone_exceeding_budget():
    """Phase 1 item 1, made structurally impossible: a budget smaller
    than vocab_size's own minimum embedding footprint must be rejected,
    not silently satisfied by an inconsistent config."""
    with pytest.raises(ValueError, match="alone requires at least"):
        GenesisModelConfig.from_param_budget(
            target_total_params=100, vocab_size=1_000_000, max_seq_len=16,
            n_layers=1, n_heads=1, n_kv_heads=1,
        )


def test_from_param_budget_finds_a_config_near_the_target():
    cfg = GenesisModelConfig.from_param_budget(
        target_total_params=10_000_000, vocab_size=1000, max_seq_len=256,
        n_layers=4, n_heads=4, n_kv_heads=2, tolerance=0.1,
    )
    assert abs(cfg.total_parameters() - 10_000_000) <= 10_000_000 * 0.1


# ----------------------------------------------------------------- RoPE --

def test_rope_angles_shape_and_rejects_odd_head_dim():
    angles = precompute_rope_angles(head_dim=8, max_seq_len=16)
    assert angles.shape == (16, 4)
    with pytest.raises(ValueError, match="even"):
        precompute_rope_angles(head_dim=7, max_seq_len=16)


def test_rope_preserves_vector_norm():
    """RoPE is a rotation -- it must preserve the L2 norm of each
    head-dim vector exactly (up to floating-point tolerance), which is
    the defining numerical property of the technique (Su et al., 2021).
    A norm-changing bug in the rotation would NOT be caught by a shape
    check alone."""
    torch.manual_seed(0)
    head_dim = 8
    x = torch.randn(1, 2, 5, head_dim)
    angles = precompute_rope_angles(head_dim, max_seq_len=5)
    rotated = apply_rope(x, angles)
    orig_norm = x.norm(dim=-1)
    new_norm = rotated.norm(dim=-1)
    assert torch.allclose(orig_norm, new_norm, atol=1e-5)


def test_rope_is_position_dependent():
    """The SAME vector at two different positions must receive different
    rotations -- otherwise RoPE would not be encoding position at all."""
    torch.manual_seed(0)
    head_dim = 8
    x = torch.randn(1, 1, 1, head_dim).expand(1, 1, 2, head_dim).clone()  # identical vector at both positions
    angles = precompute_rope_angles(head_dim, max_seq_len=2)
    rotated = apply_rope(x, angles)
    assert not torch.allclose(rotated[:, :, 0, :], rotated[:, :, 1, :])


# ------------------------------------------------------------------ GQA --

def test_repeat_kv_matches_manual_reference():
    """repeat_kv's output must exactly equal naively repeating each KV
    head n_rep times via explicit indexing -- a direct reference
    calculation, not a shape-only check."""
    torch.manual_seed(0)
    batch, n_kv_heads, seq_len, head_dim, n_rep = 2, 2, 3, 4, 3
    x = torch.randn(batch, n_kv_heads, seq_len, head_dim)
    got = repeat_kv(x, n_rep)
    expected = torch.cat([x[:, i:i + 1].repeat(1, n_rep, 1, 1) for i in range(n_kv_heads)], dim=1)
    assert torch.equal(got, expected)


def test_repeat_kv_identity_when_n_rep_is_one():
    x = torch.randn(1, 2, 3, 4)
    assert torch.equal(repeat_kv(x, 1), x)


# -------------------------------------------------------- causal masking --

def test_manual_and_sdpa_attention_backends_agree():
    """The explicit 'manual' attention path (used to reason about
    masking) must numerically agree with PyTorch's built-in SDPA path
    within floating-point tolerance -- cross-checking one real
    implementation against another, not just checking shapes."""
    torch.manual_seed(0)
    cfg = _tiny_config()
    model = GenesisTransformer(cfg)
    model.eval()
    input_ids = torch.randint(0, cfg.vocab_size, (2, 10))
    with torch.no_grad():
        out_manual = model(input_ids, attn_backend="manual")
        out_sdpa = model(input_ids, attn_backend="sdpa")
    assert torch.allclose(out_manual, out_sdpa, atol=1e-4)


def test_causal_masking_prevents_future_information_leakage():
    """The decisive adversarial check Phase 5 requires: changing a FUTURE
    token must not change any EARLIER position's output logits. Tests
    this on the real forward pass, not on the attention math in
    isolation, so it also catches a bug introduced anywhere else in the
    stack (e.g. an accidentally non-causal residual path)."""
    torch.manual_seed(0)
    cfg = _tiny_config()
    model = GenesisTransformer(cfg)
    model.eval()

    base = torch.randint(0, cfg.vocab_size, (1, 10))
    altered = base.clone()
    altered[0, -1] = (altered[0, -1] + 1) % cfg.vocab_size  # change only the LAST token

    with torch.no_grad():
        out_base = model(base)
        out_altered = model(altered)

    # Every position except the last must be bit-for-bit identical --
    # no future token can influence an earlier position's logits.
    assert torch.equal(out_base[:, :-1, :], out_altered[:, :-1, :])
    # Sanity: the last position's own output DOES depend on its own
    # (changed) input token, so the test isn't vacuously passing because
    # nothing ever changes.
    assert not torch.equal(out_base[:, -1, :], out_altered[:, -1, :])


def test_max_seq_len_is_enforced():
    cfg = _tiny_config(max_seq_len=8)
    model = GenesisTransformer(cfg)
    with pytest.raises(ValueError, match="exceeds max_seq_len"):
        model(torch.randint(0, cfg.vocab_size, (1, 9)))


# ------------------------------------------------------------- determinism --

def test_deterministic_initialization_given_fixed_seed():
    torch.manual_seed(42)
    model_a = GenesisTransformer(_tiny_config())
    torch.manual_seed(42)
    model_b = GenesisTransformer(_tiny_config())
    for (na, pa), (nb, pb) in zip(model_a.named_parameters(), model_b.named_parameters()):
        assert na == nb
        assert torch.equal(pa, pb), f"parameter {na} differs despite identical seed"


def test_different_seeds_produce_different_initialization():
    torch.manual_seed(1)
    model_a = GenesisTransformer(_tiny_config())
    torch.manual_seed(2)
    model_b = GenesisTransformer(_tiny_config())
    any_differ = any(
        not torch.equal(pa, pb)
        for (_, pa), (_, pb) in zip(model_a.named_parameters(), model_b.named_parameters())
    )
    assert any_differ


# -------------------------------------------------------------- shapes --

def test_forward_pass_output_shape():
    cfg = _tiny_config()
    model = GenesisTransformer(cfg)
    input_ids = torch.randint(0, cfg.vocab_size, (3, 7))
    with torch.no_grad():
        out = model(input_ids)
    assert out.shape == (3, 7, cfg.vocab_size)


def test_rmsnorm_output_shape_and_unit_scale_identity():
    norm = RMSNorm(dim=8)
    x = torch.randn(2, 5, 8)
    out = norm(x)
    assert out.shape == x.shape
    # With weight == 1 (fresh init) and eps negligible relative to a
    # unit-variance input, RMSNorm's output should itself have RMS ~= 1
    # per vector, the defining property of the normalization.
    rms = out.pow(2).mean(dim=-1).sqrt()
    assert torch.allclose(rms, torch.ones_like(rms), atol=0.05)


def test_generate_step_returns_no_grad_and_correct_shape():
    cfg = _tiny_config()
    model = GenesisTransformer(cfg)
    input_ids = torch.randint(0, cfg.vocab_size, (2, 5))
    next_ids = model.generate_step(input_ids, temperature=0.0)
    assert next_ids.shape == (2,)
    assert not next_ids.requires_grad


def test_unknown_attn_backend_rejected():
    cfg = _tiny_config()
    model = GenesisTransformer(cfg)
    with pytest.raises(ValueError, match="unknown attn_backend"):
        model(torch.randint(0, cfg.vocab_size, (1, 4)), attn_backend="bogus")
