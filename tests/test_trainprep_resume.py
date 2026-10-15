"""Workstream G #3, #5, #6: the toy training mechanics are deterministic, and resuming from step k is byte-identical to never stopping.
Includes the NEGATIVE CONTROLS: dropping optimizer moments / scheduler step / RNG state / data cursor at resume changes the result, which is
what proves those parts of the checkpoint actually matter. Pure Python, no GPU, no model, no network."""
from __future__ import annotations

import pytest

from orca.train.dryrun.canon import canonical_bytes
from orca.train.dryrun.ckpt import load_state, verify_checkpoint
from orca.train.dryrun.harness import ALL_STATE, Fault
from orca.train.dryrun.toy import Plan, SplitMix64, ToyEngine, initial_state, state_from_json_obj
from tests.trainprep_support import big_budget, ckpt_bytes, run

GOLDEN_FINAL_STATE_SHA256 = "5bb79b0f13b944b0e7ea966f867cbbcba85585ebcf4cc035a6dc3b1f85e424c9"


def _full(plan, tmp_path):
    return run(plan, tmp_path / "full", run_id="full")


def _cut_then_resume(plan, tmp_path, k, **resume_kw):
    run(plan, tmp_path / "cut", run_id="cut", budget=big_budget(max_steps=k))
    return run(plan, tmp_path / "cut", run_id="cut", resume=True, **resume_kw)


# ── determinism ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_same_plan_same_seed_is_bit_identical(tmp_path):
    a, b = run(Plan(), tmp_path / "a"), run(Plan(), tmp_path / "b")
    assert a.state.sha256 == b.state.sha256 and a.final_checkpoint_digest == b.final_checkpoint_digest


def test_different_seed_changes_the_result(tmp_path):
    assert run(Plan(seed=1), tmp_path / "a").state.sha256 != run(Plan(seed=2), tmp_path / "b").state.sha256


def test_golden_final_state_pins_cross_platform_determinism(tmp_path):
    """Only + - * / sqrt and 64-bit integer ops are used, so this value must be identical on every IEEE-754 platform."""
    assert run(Plan(), tmp_path / "g").state.sha256 == GOLDEN_FINAL_STATE_SHA256


def test_training_actually_learns(tmp_path):
    out = run(Plan(total_steps=60, lr=0.1, dropout_p=0.0, warmup_steps=2), tmp_path / "l")
    assert out.state.losses[-1] < out.state.losses[0] * 0.2


def test_prng_is_exact_and_portable():
    r = SplitMix64(0)        # published SplitMix64 reference vector for seed 0
    assert [r.next_u64() for _ in range(3)] == [0xE220A8397B1DCDAF, 0x6E789E6AA1B965F4, 0x06C45D188009454F]


def test_gradient_accumulation_equals_one_big_batch():
    base = dict(dropout_p=0.0, grad_clip=1e9, total_steps=1, warmup_steps=0, optimizer="sgd_momentum", checkpoint_every=1)
    small = Plan(micro_batch=2, grad_accum=4, **base)
    big = Plan(micro_batch=8, grad_accum=1, **base)
    a = ToyEngine(small).compute_step(initial_state(small))
    b = ToyEngine(big).compute_step(initial_state(big))
    assert a.examples_seen == b.examples_seen == 8
    assert max(abs(x - y) for x, y in zip(a.params, b.params)) < 1e-12


def test_gradient_accumulation_is_not_a_noop():
    one = Plan(micro_batch=4, grad_accum=1, total_steps=1, warmup_steps=0)
    two = Plan(micro_batch=4, grad_accum=2, total_steps=1, warmup_steps=0)
    assert ToyEngine(one).compute_step(initial_state(one)).examples_seen == 4
    assert ToyEngine(two).compute_step(initial_state(two)).examples_seen == 8


def test_lr_scheduler_warms_up_then_decays():
    from orca.train.dryrun.toy import lr_at
    p = Plan(lr=1.0, warmup_steps=4, total_steps=12, min_lr_ratio=0.1)
    lrs = [lr_at(p, s) for s in range(12)]
    assert lrs[0] < lrs[1] < lrs[2] < lrs[3] == 1.0 and lrs[4] > lrs[5] > lrs[11] >= 0.1 and lrs[4] == lrs[3]


# ── resume consistency (#5) ──────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("opt", ["adam", "sgd_momentum"])
@pytest.mark.parametrize("k", [1, 2, 3, 5, 7, 11])
def test_resume_from_step_k_is_byte_identical_to_uninterrupted(tmp_path, opt, k):
    plan = Plan(optimizer=opt, checkpoint_every=1)
    full = _full(plan, tmp_path)
    resumed = _cut_then_resume(plan, tmp_path, k)
    assert full.status == resumed.status == "FINISHED" and resumed.steps == plan.total_steps
    assert canonical_bytes(resumed.state.to_json_obj()) == canonical_bytes(full.state.to_json_obj())      # model, moments, scheduler, rng, cursor, losses
    assert resumed.state.sha256 == full.state.sha256
    assert ckpt_bytes(tmp_path / "cut", plan.total_steps) == ckpt_bytes(tmp_path / "full", plan.total_steps)    # final checkpoint files byte-identical
    assert resumed.final_checkpoint_digest == full.final_checkpoint_digest


def test_resume_survives_two_interruptions(tmp_path):
    plan = Plan(checkpoint_every=2)
    full = _full(plan, tmp_path)
    run(plan, tmp_path / "x", run_id="x", budget=big_budget(max_steps=3))
    run(plan, tmp_path / "x", run_id="x", resume=True, budget=big_budget(max_steps=8))
    last = run(plan, tmp_path / "x", run_id="x", resume=True)
    assert last.state.sha256 == full.state.sha256


def test_resume_restores_every_state_component_from_the_checkpoint(tmp_path):
    plan = Plan(checkpoint_every=1)
    run(plan, tmp_path / "r", run_id="r", budget=big_budget(max_steps=5))
    vc = verify_checkpoint(tmp_path / "r" / "checkpoints", "ckpt-000005", expected_plan_sha256=plan.sha256)
    st = load_state(vc, plan)
    assert st.step == 5 and st.sched_step == 5 and st.opt["t"] == 5
    assert any(x != 0.0 for x in st.opt["m"]) and any(x != 0.0 for x in st.opt["v"])
    assert st.examples_seen == 5 * plan.examples_per_step and st.tokens_seen == 5 * plan.tokens_per_step
    assert st.rng_state != initial_state(plan).rng_state and len(st.losses) == 5


# ── optimizer / scheduler state preservation + NEGATIVE CONTROLS (#6) ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("dropped", ["optimizer", "scheduler", "rng", "cursor"])
@pytest.mark.parametrize("opt", ["adam", "sgd_momentum"])
def test_negative_control_dropping_a_state_component_changes_the_result(tmp_path, dropped, opt):
    plan = Plan(optimizer=opt, checkpoint_every=1)
    full = _full(plan, tmp_path)
    broken = _cut_then_resume(plan, tmp_path, 6, restore=ALL_STATE - {dropped})
    assert broken.state.sha256 != full.state.sha256, f"dropping {dropped} had no effect -- the checkpoint would not need it"


def test_the_control_is_meaningful_restoring_everything_matches(tmp_path):
    plan = Plan(checkpoint_every=1)
    assert _cut_then_resume(plan, tmp_path, 6, restore=ALL_STATE).state.sha256 == _full(plan, tmp_path).state.sha256


def test_scheduler_step_survives_resume(tmp_path):
    plan = Plan(checkpoint_every=1, warmup_steps=6)
    broken = _cut_then_resume(plan, tmp_path / "b", 6, restore=ALL_STATE - {"scheduler"})
    good = _cut_then_resume(plan, tmp_path / "g", 6)
    assert good.state.sched_step == plan.total_steps and broken.state.sched_step == plan.total_steps - 6


def test_adam_moments_survive_resume(tmp_path):
    plan = Plan(checkpoint_every=1)
    good = _cut_then_resume(plan, tmp_path / "g", 6)
    broken = _cut_then_resume(plan, tmp_path / "b", 6, restore=ALL_STATE - {"optimizer"})
    assert good.state.opt["t"] == plan.total_steps and broken.state.opt["t"] == plan.total_steps - 6
    assert good.state.opt["m"] != broken.state.opt["m"]


# ── non-finite values ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_nan_loss_is_detected_before_commit_and_rolls_back(tmp_path):
    plan = Plan(checkpoint_every=1)
    out = run(plan, tmp_path / "n", run_id="n", fault=Fault(nan_at_step=3))
    assert out.status == "ABORTED" and out.reason == "NON_FINITE_LOSS" and out.steps == 3
    assert all(x == x for x in out.state.losses)                          # no NaN ever entered committed state
    healed = run(plan, tmp_path / "n", run_id="n", resume=True)
    assert healed.state.sha256 == _full(plan, tmp_path).state.sha256


def test_state_parser_rejects_corrupt_state():
    from orca.train.dryrun.toy import StateInvalid
    plan = Plan()
    obj = initial_state(plan).to_json_obj()
    for bad in ({**obj, "params": obj["params"][:-1]}, {**obj, "step": -1}, {**obj, "params": ["nan"] + obj["params"][1:]},
                {**obj, "extra": 1}, {**obj, "step": 3}, {**obj, "rng_state": 1 << 70}):
        with pytest.raises(StateInvalid):
            state_from_json_obj(bad, plan)
