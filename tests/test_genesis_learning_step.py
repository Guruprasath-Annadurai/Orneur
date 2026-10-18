"""
GENESIS Native Learning Engine, Phase 1, Workstream 1 tests:
`orca.genesis.training.learning_step`. Bounded, CPU-only, deterministic,
synthetic data only -- no real corpus, no GPU, no network.
"""
from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from orca.genesis.model.config import GenesisModelConfig  # noqa: E402
from orca.genesis.model.transformer import GenesisTransformer  # noqa: E402
from orca.genesis.training.learning_step import (  # noqa: E402
    ExecutionCapability,
    MissingExecutionCapabilityError,
    NonFiniteTrainingSignalError,
    ResourceLimitExceededError,
    StepResult,
    TrainingStepConfig,
    TrainingStepEngine,
    set_deterministic_seed,
)

TINY_CFG = GenesisModelConfig(vocab_size=48, d_model=16, n_layers=2, n_heads=2, n_kv_heads=1, d_ff=32, max_seq_len=16)
# AUDIT-P0-02: step() now requires a real ExecutionCapability. This file unit-tests
# TrainingStepEngine's own mechanics in isolation, exactly as this phase's directive
# permits ("synthetic, ephemeral CPU tests may continue within existing authorized
# test boundaries") -- using the explicit, named, grep-able test-only bypass, never
# a real one obtained through learning_governance.
TEST_CAP = ExecutionCapability.for_unchecked_synthetic_test()


def _make_engine(**overrides) -> TrainingStepEngine:
    set_deterministic_seed(overrides.pop("seed", 0))
    model = GenesisTransformer(TINY_CFG)
    cfg = TrainingStepConfig(**{"warmup_steps": 2, "total_steps": 20, **overrides})
    return TrainingStepEngine(model, cfg)


def _batch(batch_size=2, seq_len=6, seed=0):
    g = torch.Generator().manual_seed(seed)
    ids = torch.randint(0, TINY_CFG.vocab_size, (batch_size, seq_len), generator=g)
    return ids, ids.clone()


def test_forward_pass_produces_finite_loss():
    engine = _make_engine()
    input_ids, labels = _batch()
    result = engine.step(input_ids, labels, capability=TEST_CAP)
    assert torch.isfinite(torch.tensor(result.microbatch_loss))


def test_single_accum_step_applies_immediately():
    engine = _make_engine(grad_accum_steps=1)
    input_ids, labels = _batch()
    result = engine.step(input_ids, labels, capability=TEST_CAP)
    assert result.applied is True
    assert result.global_step == 0
    assert result.lr is not None
    assert result.grad_norm is not None


def test_gradient_accumulation_only_applies_on_the_final_microbatch():
    engine = _make_engine(grad_accum_steps=3)
    input_ids, labels = _batch()
    r1 = engine.step(input_ids, labels, capability=TEST_CAP)
    r2 = engine.step(input_ids, labels, capability=TEST_CAP)
    r3 = engine.step(input_ids, labels, capability=TEST_CAP)
    assert (r1.applied, r2.applied, r3.applied) == (False, False, True)
    assert (r1.accumulation_index, r2.accumulation_index, r3.accumulation_index) == (0, 1, 2)
    assert r3.global_step == 0  # the FIRST applied step is global_step 0, completed on the 3rd microbatch


def test_parameters_actually_change_after_an_applied_step():
    engine = _make_engine(grad_accum_steps=1)
    before = {n: p.clone() for n, p in engine.model.named_parameters()}
    input_ids, labels = _batch()
    engine.step(input_ids, labels, capability=TEST_CAP)
    changed = [n for n, p in engine.model.named_parameters() if not torch.equal(before[n], p)]
    assert changed, "no parameter changed after an applied optimizer step"


def test_parameters_do_not_change_before_the_accumulation_cycle_completes():
    engine = _make_engine(grad_accum_steps=4)
    before = {n: p.clone() for n, p in engine.model.named_parameters()}
    input_ids, labels = _batch()
    engine.step(input_ids, labels, capability=TEST_CAP)
    engine.step(input_ids, labels, capability=TEST_CAP)
    assert all(torch.equal(before[n], p) for n, p in engine.model.named_parameters())


def test_zero_grad_ordering_grads_do_not_leak_into_the_next_cycle():
    """After an applied step, the very first microbatch of the NEXT
    cycle must start from zeroed gradients -- not accumulate on top of
    the gradients that were just applied and should have been cleared."""
    engine = _make_engine(grad_accum_steps=1)
    input_ids, labels = _batch()
    engine.step(input_ids, labels, capability=TEST_CAP)
    for p in engine.model.parameters():
        if p.grad is not None:
            assert torch.all(p.grad == 0), "a stale gradient leaked across zero_grad()"


def test_determinism_same_seed_same_model_same_steps_bit_identical():
    engine_a = _make_engine(seed=123, grad_accum_steps=1)
    engine_b = _make_engine(seed=123, grad_accum_steps=1)
    input_ids, labels = _batch(seed=5)
    for _ in range(3):
        ra = engine_a.step(input_ids, labels, capability=TEST_CAP)
        rb = engine_b.step(input_ids, labels, capability=TEST_CAP)
        assert ra.microbatch_loss == rb.microbatch_loss
    for (na, pa), (nb, pb) in zip(engine_a.model.named_parameters(), engine_b.model.named_parameters()):
        assert na == nb
        assert torch.equal(pa, pb), f"parameter {na} diverged between two identically-seeded runs"


def test_different_seeds_produce_different_initial_parameters():
    engine_a = _make_engine(seed=1)
    engine_b = _make_engine(seed=2)
    assert any(
        not torch.equal(pa, pb)
        for (_, pa), (_, pb) in zip(engine_a.model.named_parameters(), engine_b.model.named_parameters())
    )


def test_non_finite_loss_is_detected_and_raises_before_any_optimizer_step():
    engine = _make_engine(grad_accum_steps=1)
    before = {n: p.clone() for n, p in engine.model.named_parameters()}
    # Force a NaN loss by feeding an out-of-vocab id that still passes
    # through embedding lookup bounds-checking at the tensor level --
    # instead, directly corrupt the model's output path by monkeypatching
    # the loss computation input: simplest reliable way is to inject a
    # NaN into the model's embedding weights, which deterministically
    # propagates to a NaN loss.
    with torch.no_grad():
        engine.model.tok_embeddings.weight[0, 0] = float("nan")
    input_ids = torch.zeros((1, 4), dtype=torch.long)
    labels = input_ids.clone()
    with pytest.raises(NonFiniteTrainingSignalError):
        engine.step(input_ids, labels, capability=TEST_CAP)
    assert all(torch.equal(before[n], p) for n, p in engine.model.named_parameters() if n != "tok_embeddings.weight")


def test_resource_limit_rejects_an_oversized_batch():
    engine = _make_engine()
    huge = torch.zeros((10, 200_000), dtype=torch.long)
    with pytest.raises(ResourceLimitExceededError):
        engine.step(huge, huge, capability=TEST_CAP)


def test_max_steps_ceiling_is_enforced():
    engine = _make_engine(grad_accum_steps=1, max_steps=1)
    input_ids, labels = _batch()
    r = engine.step(input_ids, labels, capability=TEST_CAP)
    assert r.applied and r.global_step == 0
    with pytest.raises(ResourceLimitExceededError):
        engine.step(input_ids, labels, capability=TEST_CAP)


def test_training_step_config_rejects_invalid_values():
    with pytest.raises(ValueError):
        TrainingStepConfig(grad_accum_steps=0)
    with pytest.raises(ValueError):
        TrainingStepConfig(max_grad_norm=0)
    with pytest.raises(ValueError):
        TrainingStepConfig(max_steps=0)


def test_learning_rate_follows_the_configured_warmup_schedule():
    engine = _make_engine(grad_accum_steps=1, warmup_steps=5, total_steps=50, max_lr=1e-3)
    input_ids, labels = _batch()
    lrs = [engine.step(input_ids, labels, capability=TEST_CAP).lr for _ in range(5)]
    assert lrs == sorted(lrs), "learning rate should monotonically increase through warmup"
    assert lrs[-1] <= 1e-3 + 1e-12


# ==================================================================================
# Antigravity Audit #074 remediation: AUDIT-P0-02 (execution capability requirement)
# ==================================================================================

def test_p0_02_step_without_any_capability_is_rejected():
    engine = _make_engine()
    input_ids, labels = _batch()
    with pytest.raises(TypeError):
        engine.step(input_ids, labels)  # type: ignore[call-arg]


def test_p0_02_step_with_a_non_capability_object_is_rejected():
    engine = _make_engine()
    input_ids, labels = _batch()
    with pytest.raises(MissingExecutionCapabilityError):
        engine.step(input_ids, labels, capability="not-a-real-capability")  # type: ignore[arg-type]


def test_p0_02_step_with_another_engines_capability_token_is_rejected():
    engine_a = _make_engine(seed=1)
    engine_b = _make_engine(seed=2)
    input_ids, labels = _batch()
    foreign_capability = engine_b._issue_capability_for_governance()
    with pytest.raises(MissingExecutionCapabilityError):
        engine_a.step(input_ids, labels, capability=foreign_capability)


def test_p0_02_the_engines_own_issued_capability_is_accepted():
    engine = _make_engine()
    input_ids, labels = _batch()
    capability = engine._issue_capability_for_governance()
    result = engine.step(input_ids, labels, capability=capability)
    assert result.applied is True
