"""Training-mathematics qualification on tiny CPU tensors.

Tolerances are explicit. Nothing here is a training run or a corpus fit.
"""
from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from orca.genesis.model.config import GenesisModelConfig  # noqa: E402
from orca.genesis.model.transformer import GenesisTransformer  # noqa: E402
from orca.genesis.training.learning_step import (  # noqa: E402
    ExecutionCapability,
    NonFiniteTrainingSignalError,
    TrainingStepConfig,
    TrainingStepEngine,
)
from orca.genesis.training.math_qualification import (  # noqa: E402
    finite_difference_gradients,
    reference_adamw_step,
    supervised_token_count,
)
from orca.genesis.training.primitives import (  # noqa: E402
    OptimizerConfig,
    OptimizerStateCorruptionError,
    TrainingState,
    build_optimizer,
    clip_grad_norm,
    grouped_parameters,
)


TINY = GenesisModelConfig(
    vocab_size=32, d_model=16, n_layers=1, n_heads=2, n_kv_heads=2, d_ff=32, max_seq_len=8, tie_embeddings=True,
)


def _model(seed: int = 0) -> GenesisTransformer:
    torch.manual_seed(seed)
    return GenesisTransformer(TINY)


def test_finite_difference_matches_backward_within_absolute_tolerance():
    model = _model()
    ids = torch.randint(0, TINY.vocab_size, (2, 6))
    labels = ids.clone()
    report = finite_difference_gradients(model, ids, labels, epsilon=1e-3, atol=2e-3)
    assert report["checked_elements"] > 0
    assert report["max_abs_error"] <= 2e-3


def test_one_step_adamw_matches_the_reference_formula():
    torch.manual_seed(0)
    weight = torch.nn.Parameter(torch.tensor([1.0, -2.0, 0.5]))
    opt = torch.optim.AdamW([{"params": [weight], "weight_decay": 0.1}], lr=0.01, betas=(0.9, 0.95), eps=1e-8)
    grad = torch.tensor([0.3, -0.1, 0.0])
    weight.grad = grad.clone()
    opt.step()
    updated, _m, _v = reference_adamw_step(
        torch.tensor([1.0, -2.0, 0.5]),
        grad,
        torch.zeros(3),
        torch.zeros(3),
        step=1,
        lr=0.01,
        beta1=0.9,
        beta2=0.95,
        eps=1e-8,
        weight_decay=0.1,
    )
    assert torch.allclose(weight.detach(), updated, atol=1e-6, rtol=1e-6)


def test_weight_decay_does_not_apply_to_one_dimensional_parameters():
    model = _model()
    opt = build_optimizer(model, OptimizerConfig(lr=0.1, weight_decay=0.2))
    groups = grouped_parameters(model, 0.2)
    assert groups[0]["weight_decay"] == 0.2
    assert groups[1]["weight_decay"] == 0.0
    before_norm = {name: p.detach().clone() for name, p in model.named_parameters() if p.dim() < 2}
    before_matrix = next(p.detach().clone() for p in model.parameters() if p.dim() >= 2)
    for p in model.parameters():
        p.grad = torch.zeros_like(p)
    opt.step()
    for name, p in model.named_parameters():
        if p.dim() < 2:
            assert torch.equal(p.detach(), before_norm[name])
    matrix = next(p.detach() for p in model.parameters() if p.dim() >= 2)
    assert not torch.equal(matrix, before_matrix)


def test_zero_grad_does_not_leave_a_stale_gradient_for_the_next_step():
    model = _model()
    cfg = TrainingStepConfig(
        grad_accum_steps=1, warmup_steps=1, total_steps=4, max_lr=1e-2, min_lr=0.0,
        optimizer=OptimizerConfig(lr=1e-2, weight_decay=0.0), attn_backend="manual",
    )
    engine = TrainingStepEngine(model, cfg)
    cap = ExecutionCapability.for_unchecked_synthetic_test()
    ids = torch.randint(0, TINY.vocab_size, (1, 4))
    engine.step(ids, ids.clone(), cap)
    assert all(p.grad is None for p in model.parameters())


def test_gradient_clipping_reports_the_preclip_norm_and_limits_the_postclip_norm():
    model = _model()
    for p in model.parameters():
        p.grad = torch.ones_like(p) * 10
    pre = clip_grad_norm(model, 0.5)
    assert pre > 0.5
    total = torch.nn.utils.clip_grad_norm_(model.parameters(), 1e9)
    assert float(total) == pytest.approx(0.5, rel=1e-4)


def test_nan_gradient_fails_the_step_before_the_optimizer_moves_parameters():
    model = _model()
    cfg = TrainingStepConfig(
        grad_accum_steps=1, warmup_steps=0, total_steps=4, max_lr=1e-3,
        optimizer=OptimizerConfig(lr=1e-3, weight_decay=0.0), attn_backend="manual", max_steps=4,
    )
    # warmup_steps must be < total_steps. 0 is allowed.
    engine = TrainingStepEngine(model, cfg)
    ids = torch.randint(0, TINY.vocab_size, (1, 4))
    with torch.no_grad():
        model.tok_embeddings.weight[0, 0] = float("nan")
    before = {name: p.detach().clone() for name, p in model.named_parameters()}
    with pytest.raises(NonFiniteTrainingSignalError):
        engine.step(ids, ids.clone(), ExecutionCapability.for_unchecked_synthetic_test())
    for name, p in model.named_parameters():
        assert torch.allclose(p.detach(), before[name], equal_nan=True)


def test_supervised_token_count_matches_the_causal_shift():
    labels = torch.tensor([[1, 2, -100, 4]])
    assert supervised_token_count(labels) == 2
    assert supervised_token_count(torch.tensor([[7]])) == 0


def test_accumulation_of_equal_microbatches_matches_the_averaged_gradient():
    """Assumption: equal microbatch sizes, mean-reduced loss, and the engine's divide-by-N.

    This is not a claim that gradient accumulation equals one concatenated batch.
    """
    torch.manual_seed(0)
    model_a = _model(0)
    model_b = GenesisTransformer(TINY)
    model_b.load_state_dict(model_a.state_dict())
    batches = [torch.randint(0, TINY.vocab_size, (1, 4)) for _ in range(2)]
    from orca.genesis.training.primitives import causal_lm_loss

    model_a.zero_grad(set_to_none=True)
    losses = []
    for batch in batches:
        loss = causal_lm_loss(model_a(batch, attn_backend="manual"), batch)
        (loss / 2).backward()
        losses.append(loss.detach())
    grad_a = {name: p.grad.detach().clone() for name, p in model_a.named_parameters() if p.grad is not None}

    model_b.zero_grad(set_to_none=True)
    mean_loss = sum(causal_lm_loss(model_b(batch, attn_backend="manual"), batch) for batch in batches) / 2
    mean_loss.backward()
    for name, p in model_b.named_parameters():
        if p.grad is None:
            assert name not in grad_a
            continue
        assert torch.allclose(p.grad, grad_a[name], atol=1e-5, rtol=1e-5)


def test_optimizer_state_corruption_is_rejected_on_restore():
    model = _model()
    opt = build_optimizer(model, OptimizerConfig())
    ids_loss_param = next(model.parameters())
    ids_loss_param.grad = torch.zeros_like(ids_loss_param)
    for p in model.parameters():
        if p.grad is None:
            p.grad = torch.zeros_like(p)
    opt.step()
    state = TrainingState.capture(step=1, epoch=0, dataloader_position=0, model=model, optimizer=opt)
    slot = next(iter(state.optimizer_state_dict["state"].values()))
    slot["exp_avg"] = torch.ones(1)
    with pytest.raises(OptimizerStateCorruptionError, match="shape"):
        state.restore(model=model, optimizer=opt)


def test_optimizer_nan_moment_is_rejected():
    model = _model()
    opt = build_optimizer(model, OptimizerConfig())
    for p in model.parameters():
        p.grad = torch.zeros_like(p)
    opt.step()
    state = TrainingState.capture(step=1, epoch=0, dataloader_position=0, model=model, optimizer=opt)
    slot = next(iter(state.optimizer_state_dict["state"].values()))
    slot["exp_avg"] = torch.full_like(slot["exp_avg"], float("nan"))
    with pytest.raises(OptimizerStateCorruptionError, match="not finite"):
        state.restore(model=model, optimizer=opt)


def test_repeated_interruption_stays_within_a_documented_tolerance():
    """Three save/restore cycles versus an uninterrupted engine.

    Comparison is allclose with atol=1e-6, rtol=1e-5. On this CPU run the
    difference may be zero; that observation is not a cross-hardware
    bit-exact guarantee.
    """
    def run(interrupt: bool):
        torch.manual_seed(4)
        model = _model(4)
        cfg = TrainingStepConfig(
            grad_accum_steps=1, warmup_steps=1, total_steps=8, max_lr=1e-3, min_lr=0.0,
            optimizer=OptimizerConfig(lr=1e-3, weight_decay=0.0), attn_backend="manual",
        )
        engine = TrainingStepEngine(model, cfg)
        cap = ExecutionCapability.for_unchecked_synthetic_test()
        batches = [torch.randint(0, TINY.vocab_size, (1, 4)) for _ in range(3)]
        if not interrupt:
            for batch in batches:
                engine.step(batch, batch.clone(), cap)
            return {name: p.detach().clone() for name, p in model.named_parameters()}
        engine.step(batches[0], batches[0].clone(), cap)
        saved = TrainingState.capture(
            step=engine.global_step, epoch=0, dataloader_position=1, model=model, optimizer=engine.optimizer,
        )
        torch.manual_seed(99)
        resumed_model = _model(99)
        resumed = TrainingStepEngine(resumed_model, cfg)
        saved.restore(model=resumed_model, optimizer=resumed.optimizer)
        resumed.global_step = saved.step
        cap2 = ExecutionCapability.for_unchecked_synthetic_test()
        resumed.step(batches[1], batches[1].clone(), cap2)
        saved2 = TrainingState.capture(
            step=resumed.global_step, epoch=0, dataloader_position=2, model=resumed_model, optimizer=resumed.optimizer,
        )
        third_model = _model(123)
        third = TrainingStepEngine(third_model, cfg)
        saved2.restore(model=third_model, optimizer=third.optimizer)
        third.global_step = saved2.step
        third.step(batches[2], batches[2].clone(), ExecutionCapability.for_unchecked_synthetic_test())
        return {name: p.detach().clone() for name, p in third_model.named_parameters()}

    plain = run(False)
    broken = run(True)
    for name in plain:
        assert torch.allclose(plain[name], broken[name], atol=1e-6, rtol=1e-5)


def test_scheduler_step_used_by_the_engine_is_the_pre_increment_global_step():
    model = _model()
    cfg = TrainingStepConfig(
        grad_accum_steps=1, warmup_steps=4, total_steps=8, max_lr=1e-2, min_lr=0.0,
        optimizer=OptimizerConfig(lr=1e-2, weight_decay=0.0), attn_backend="manual",
    )
    engine = TrainingStepEngine(model, cfg)
    cap = ExecutionCapability.for_unchecked_synthetic_test()
    ids = torch.randint(0, TINY.vocab_size, (1, 4))
    first = engine.step(ids, ids.clone(), cap)
    second = engine.step(ids, ids.clone(), cap)
    from orca.genesis.training.primitives import cosine_warmup_lr
    assert first.lr == pytest.approx(cosine_warmup_lr(0, warmup_steps=4, total_steps=8, max_lr=1e-2))
    assert second.lr == pytest.approx(cosine_warmup_lr(1, warmup_steps=4, total_steps=8, max_lr=1e-2))
