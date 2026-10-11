"""Workstream G #8 (and register P2-4): resource budget + hard-stop controls. Default caps are 0 => nothing runs; every cap is enforced BEFORE
the offending step; the kill switch and wall clock can abort an in-flight step, which is rolled back to the last committed state."""
from __future__ import annotations

import math

import pytest

from orca.train.dryrun.budget import BudgetInvalid, BudgetMeter, HardStop, KillSwitch, ResourceBudget
from orca.train.dryrun.ckpt import load_state, verify_checkpoint
from orca.train.dryrun.harness import Fault
from orca.train.dryrun.ledger import RunLedger
from orca.train.dryrun.toy import Plan, ToyEngine
from tests.trainprep_support import big_budget, run

PLAN = Plan(checkpoint_every=1)


@pytest.fixture
def step_counter(monkeypatch):
    """Counts how many optimizer steps were actually COMPUTED (committed or not)."""
    calls = []
    orig = ToyEngine.compute_step

    def spy(self, state, *a, **kw):
        calls.append(state.step)
        return orig(self, state, *a, **kw)
    monkeypatch.setattr(ToyEngine, "compute_step", spy)
    return calls


def _ledger_types(root):
    return [r["body"]["type"] for r in RunLedger(root / "ledger.jsonl").records()]


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


# ── defaults and validation ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_default_budget_is_all_zero_and_nothing_runs(tmp_path, step_counter):
    assert ResourceBudget().is_zero
    out = run(PLAN, tmp_path / "z", budget=ResourceBudget())
    assert out.status == "REFUSED" and out.reason == "ZERO_BUDGET" and out.steps == 0 and out.state is None
    assert step_counter == [] and not (tmp_path / "z" / "checkpoints").exists()
    assert _ledger_types(tmp_path / "z") == ["run_refused", "manifest_sealed"]


@pytest.mark.parametrize("zeroed", ["max_steps", "max_tokens", "max_wall_clock_s", "max_spend_usd"])
def test_any_single_zero_cap_means_no_allowance_not_unlimited(tmp_path, step_counter, zeroed):
    out = run(PLAN, tmp_path / "z", budget=big_budget(**{zeroed: 0}))
    assert out.status == "REFUSED" and step_counter == []


@pytest.mark.parametrize("field,bad", [("max_steps", -1), ("max_steps", True), ("max_steps", 1.5), ("max_tokens", -5), ("max_wall_clock_s", -1.0),
                                        ("max_wall_clock_s", math.nan), ("max_wall_clock_s", math.inf), ("max_spend_usd", -0.01),
                                        ("max_spend_usd", math.nan), ("max_spend_usd", "1"), ("sim_cost_usd_per_step", -1)])
def test_invalid_caps_are_refused_not_coerced(field, bad):
    with pytest.raises(BudgetInvalid):
        ResourceBudget(**{field: bad})


# ── each cap is enforced BEFORE the offending step ───────────────────────────────────────────────────────────────────────────────

def test_step_cap_stops_before_the_next_step_is_computed(tmp_path, step_counter):
    out = run(PLAN, tmp_path / "s", budget=big_budget(max_steps=5))
    assert (out.status, out.reason, out.steps) == ("STOPPED", "STEP_CAP", 5)
    assert step_counter == [0, 1, 2, 3, 4]                                  # a sixth step was never even started


def test_token_cap_exceeded_mid_run_never_overshoots(tmp_path, step_counter):
    assert PLAN.tokens_per_step == 64
    out = run(PLAN, tmp_path / "t", budget=big_budget(max_tokens=200))
    assert (out.reason, out.steps, out.state.tokens_seen) == ("TOKEN_CAP", 3, 192) and step_counter == [0, 1, 2]


def test_token_cap_exactly_met_is_allowed(tmp_path):
    out = run(PLAN, tmp_path / "t", budget=big_budget(max_tokens=192))
    assert out.steps == 3 and out.reason == "TOKEN_CAP"


def test_spend_cap_exceeded_mid_run(tmp_path, step_counter):
    out = run(PLAN, tmp_path / "p", budget=big_budget(max_spend_usd=0.10, sim_cost_usd_per_step=0.03))
    assert (out.reason, out.steps, out.usage["spend_micro_usd"]) == ("SPEND_CAP", 3, 90_000) and step_counter == [0, 1, 2]


def test_spend_arithmetic_is_exact_not_float(tmp_path):
    """0.1 * 3 == 0.30000000000000004 in floats; with integer micro-USD exactly three steps fit a 0.30 cap."""
    out = run(PLAN, tmp_path / "p", budget=big_budget(max_spend_usd=0.30, sim_cost_usd_per_step=0.10))
    assert out.steps == 3 and out.reason == "SPEND_CAP"


def test_spend_above_the_configured_cap_is_refused_including_cap_zero(tmp_path, step_counter):
    """Register P2-4: a spend above the configured cap is refused (the cap value may remain 0)."""
    assert run(PLAN, tmp_path / "a", budget=big_budget(max_spend_usd=0)).status == "REFUSED"
    out = run(PLAN, tmp_path / "b", budget=big_budget(max_spend_usd=0.005, sim_cost_usd_per_step=0.01))
    assert (out.status, out.reason, out.steps) == ("STOPPED", "SPEND_CAP", 0) and step_counter == []


def test_wall_clock_cap_checked_before_a_step(tmp_path, step_counter):
    clk = Clock()
    out = run(PLAN, tmp_path / "w", budget=big_budget(max_wall_clock_s=5), clock=clk, fault=Fault(on_micro=lambda s, m: setattr(clk, "t", 6.0 * (s + 1))))
    # step 0's micro-batches push the clock past the cap -> the in-flight step is rolled back, nothing committed
    assert (out.status, out.reason, out.steps) == ("STOPPED", "WALL_CLOCK_CAP", 0)


def test_wall_clock_exceeded_mid_run_rolls_back_the_in_flight_step(tmp_path):
    clk = Clock()

    def tick(step, micro):
        clk.t += 10.0                                                       # every micro-batch costs 10 "seconds"; a step is 2 micro-batches
    out = run(PLAN, tmp_path / "w", budget=big_budget(max_wall_clock_s=35), clock=clk, fault=Fault(on_micro=tick))
    assert (out.status, out.reason, out.steps) == ("STOPPED", "WALL_CLOCK_CAP", 1)
    ref = run(PLAN, tmp_path / "ref", budget=big_budget(max_steps=1))
    assert out.state.sha256 == ref.state.sha256                             # state is exactly the last COMMITTED step, no partial step 2
    assert "step_aborted" in _ledger_types(tmp_path / "w")


# ── kill switch ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_kill_switch_file_present_at_start_prevents_any_step(tmp_path, step_counter):
    flag = tmp_path / "KILL"
    flag.write_text("")
    out = run(PLAN, tmp_path / "k", budget=big_budget(kill_switch_path=flag))
    assert (out.status, out.reason, out.steps) == ("STOPPED", "KILL_SWITCH", 0) and step_counter == []


def test_kill_switch_flag_object(tmp_path, step_counter):
    ks = KillSwitch()
    ks.engage()
    assert run(PLAN, tmp_path / "k", kill_switch=ks).reason == "KILL_SWITCH" and step_counter == []


def test_dangling_symlink_kill_switch_still_counts_as_engaged(tmp_path):
    flag = tmp_path / "KILL"
    flag.symlink_to(tmp_path / "nowhere")
    assert KillSwitch(flag).engaged


def test_kill_switch_engaged_mid_step_rolls_back_and_resume_finishes_identically(tmp_path):
    flag = tmp_path / "KILL"
    out = run(PLAN, tmp_path / "k", run_id="k", budget=big_budget(kill_switch_path=flag),
              fault=Fault(on_micro=lambda s, m: flag.write_text("") if (s, m) == (2, 1) else None))
    assert (out.status, out.reason, out.steps) == ("STOPPED", "KILL_SWITCH", 2)
    assert out.state.sha256 == run(PLAN, tmp_path / "ref", budget=big_budget(max_steps=2)).state.sha256
    types = _ledger_types(tmp_path / "k")
    assert types.count("step_committed") == 2 and "step_aborted" in types and types[-2:] == ["run_stopped", "manifest_sealed"]
    flag.unlink()
    healed = run(PLAN, tmp_path / "k", run_id="k", budget=big_budget(kill_switch_path=flag), resume=True)
    assert healed.status == "FINISHED" and healed.state.sha256 == run(PLAN, tmp_path / "full", run_id="full").state.sha256


# ── interrupted-run rollback ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_exception_mid_accumulation_rolls_back_to_the_last_committed_state(tmp_path):
    out = run(PLAN, tmp_path / "e", run_id="e", fault=Fault(raise_at=(2, 1)))
    assert (out.status, out.reason, out.steps) == ("ABORTED", "EXCEPTION:RuntimeError", 2)
    assert out.state.sha256 == run(PLAN, tmp_path / "ref", budget=big_budget(max_steps=2)).state.sha256
    vc = verify_checkpoint(tmp_path / "e" / "checkpoints", "ckpt-000002", expected_plan_sha256=PLAN.sha256)       # rollback target persisted
    assert load_state(vc, PLAN).sha256 == out.state.sha256
    healed = run(PLAN, tmp_path / "e", run_id="e", resume=True)
    assert healed.state.sha256 == run(PLAN, tmp_path / "full", run_id="full").state.sha256


def test_keyboard_interrupt_is_recorded_rolled_back_and_re_raised(tmp_path):
    def ctrl_c(step, micro):
        if (step, micro) == (1, 0):
            raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        run(PLAN, tmp_path / "i", run_id="i", fault=Fault(on_micro=ctrl_c))
    types = _ledger_types(tmp_path / "i")
    assert "step_aborted" in types and "run_stopped" in types and types.count("step_committed") == 1
    healed = run(PLAN, tmp_path / "i", run_id="i", resume=True)
    assert healed.state.sha256 == run(PLAN, tmp_path / "full", run_id="full").state.sha256


def test_caps_are_cumulative_across_resume_not_reset_by_it(tmp_path):
    run(PLAN, tmp_path / "c", run_id="c", budget=big_budget(max_steps=5))
    out = run(PLAN, tmp_path / "c", run_id="c", resume=True, budget=big_budget(max_steps=8))
    assert (out.status, out.reason, out.steps) == ("STOPPED", "STEP_CAP", 8)          # 3 more, not 8 more


def test_token_and_spend_caps_are_cumulative_across_resume_too(tmp_path):
    run(PLAN, tmp_path / "c", run_id="c", budget=big_budget(max_steps=5))
    out = run(PLAN, tmp_path / "c", run_id="c", resume=True, budget=big_budget(max_tokens=64 * 7))
    assert out.reason == "TOKEN_CAP" and out.steps == 7
    out2 = run(PLAN, tmp_path / "d", run_id="d", budget=big_budget(max_steps=4))
    out3 = run(PLAN, tmp_path / "d", run_id="d", resume=True, budget=big_budget(max_spend_usd=0.06, sim_cost_usd_per_step=0.01))
    assert out2.steps == 4 and out3.reason == "SPEND_CAP" and out3.steps == 6


def test_budget_meter_is_pure_accounting():
    m = BudgetMeter(big_budget(max_steps=2), clock=lambda: 0.0)
    m.check_before_step(1)
    m.commit_step(1)
    m.check_before_step(1)
    m.commit_step(1)
    with pytest.raises(HardStop) as e:
        m.check_before_step(1)
    assert e.value.reason == "STEP_CAP"
