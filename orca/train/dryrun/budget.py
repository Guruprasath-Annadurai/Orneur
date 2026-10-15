"""Resource budget + hard-stop controls for the synthetic harness (and the template for a real runner).

Semantics (all tested in tests/test_trainprep_budget.py):
  * A cap of 0 means "no allowance", NEVER "unlimited". The default budget is all zeros, so by default nothing runs.
  * Every cap is checked BEFORE the step that would exceed it (the offending step is never started, let alone committed): steps, tokens,
    simulated spend, wall clock. The kill switch (a flag object or a file that merely has to exist) is checked before every step AND before
    every micro-batch, so it can abort an in-flight step, which the harness then rolls back to the last committed state.
  * Invalid caps (negative, NaN, bool, non-number) are refused, not coerced.
  * Spend here is SIMULATED (cost per step is a declared synthetic number). No money, provider or GPU is involved. Spend uses integer
    micro-USD so repeated float addition cannot let a cap be exceeded by rounding.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Callable

STOP_REASONS = ("ZERO_BUDGET", "KILL_SWITCH", "STEP_CAP", "TOKEN_CAP", "SPEND_CAP", "WALL_CLOCK_CAP")


class HardStop(Exception):
    """Raised to stop a run. `.reason` is one of STOP_REASONS. It is raised BEFORE the offending work starts."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason, self.detail = reason, detail
        super().__init__(reason + (": " + detail if detail else ""))


class BudgetInvalid(ValueError):
    pass


def _micro(usd, what: str, rounding) -> int:
    if isinstance(usd, bool) or not isinstance(usd, (int, float, Decimal)) or (isinstance(usd, float) and not math.isfinite(usd)) or usd < 0:
        raise BudgetInvalid(f"{what} must be a finite non-negative number")
    return int((Decimal(str(usd)) * 1_000_000).to_integral_value(rounding=rounding))


@dataclass(frozen=True)
class ResourceBudget:
    max_steps: int = 0
    max_tokens: int = 0
    max_wall_clock_s: float = 0.0
    max_spend_usd: float = 0.0
    sim_cost_usd_per_step: float = 0.0
    kill_switch_path: Path | None = None

    def __post_init__(self):
        for n in ("max_steps", "max_tokens"):
            v = getattr(self, n)
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise BudgetInvalid(f"{n} must be a non-negative int")
        if isinstance(self.max_wall_clock_s, bool) or not isinstance(self.max_wall_clock_s, (int, float)) or not math.isfinite(self.max_wall_clock_s) \
                or self.max_wall_clock_s < 0:
            raise BudgetInvalid("max_wall_clock_s must be a finite non-negative number")
        _micro(self.max_spend_usd, "max_spend_usd", ROUND_FLOOR)
        _micro(self.sim_cost_usd_per_step, "sim_cost_usd_per_step", ROUND_CEILING)

    @property
    def is_zero(self) -> bool:
        return not (self.max_steps and self.max_tokens and self.max_wall_clock_s and self.max_spend_usd)

    def as_dict(self) -> dict:
        return {"max_steps": self.max_steps, "max_tokens": self.max_tokens, "max_wall_clock_s": self.max_wall_clock_s,
                "max_spend_usd": self.max_spend_usd, "sim_cost_usd_per_step": self.sim_cost_usd_per_step,
                "kill_switch_configured": self.kill_switch_path is not None}


class KillSwitch:
    """A process-local flag AND/OR a file whose mere existence engages it. Never cleared by the harness."""

    def __init__(self, path=None):
        self.path = Path(path) if path is not None else None
        self._flag = False

    def engage(self) -> None:
        self._flag = True

    @property
    def engaged(self) -> bool:
        if self._flag:
            return True
        if self.path is not None:
            try:
                return self.path.exists() or self.path.is_symlink()
            except OSError:
                return True                  # cannot tell -> fail closed
        return False


class BudgetMeter:
    def __init__(self, budget: ResourceBudget, *, clock: Callable[[], float] = time.monotonic, kill_switch: KillSwitch | None = None,
                 wall_clock_cap_override_s: float | None = None, initial_steps: int = 0, initial_tokens: int = 0,
                 initial_spend_micro: int = 0):
        self.budget = budget
        self.clock = clock
        self.kill = kill_switch or KillSwitch(budget.kill_switch_path)
        cap = budget.max_wall_clock_s
        if wall_clock_cap_override_s is not None:
            cap = min(cap, wall_clock_cap_override_s) if cap else cap        # an authorized grant can only TIGHTEN the wall clock
        self.wall_cap_s = cap
        self.t0 = clock()
        # A resumed run starts from what the ledger says was already consumed, so resuming cannot be used to reset the step/token/spend caps.
        self.steps, self.tokens, self.spend_micro = initial_steps, initial_tokens, initial_spend_micro
        self._cap_spend_micro = _micro(budget.max_spend_usd, "max_spend_usd", ROUND_FLOOR)
        self._step_cost_micro = _micro(budget.sim_cost_usd_per_step, "sim_cost_usd_per_step", ROUND_CEILING)

    @property
    def elapsed_s(self) -> float:
        return self.clock() - self.t0

    def check_micro(self) -> None:
        """Called before each micro-batch inside a step: only the kill switch and the wall clock can abort an in-flight step."""
        if self.kill.engaged:
            raise HardStop("KILL_SWITCH")
        if self.elapsed_s >= self.wall_cap_s:
            raise HardStop("WALL_CLOCK_CAP", f"{self.elapsed_s:.3f}s >= {self.wall_cap_s}s")

    def check_before_step(self, step_tokens: int) -> None:
        b = self.budget
        if b.is_zero or self.wall_cap_s <= 0:
            raise HardStop("ZERO_BUDGET")
        if self.kill.engaged:
            raise HardStop("KILL_SWITCH")
        if self.steps + 1 > b.max_steps:
            raise HardStop("STEP_CAP", f"step {self.steps + 1} > {b.max_steps}")
        if self.tokens + step_tokens > b.max_tokens:
            raise HardStop("TOKEN_CAP", f"{self.tokens + step_tokens} > {b.max_tokens}")
        if self.spend_micro + self._step_cost_micro > self._cap_spend_micro:
            raise HardStop("SPEND_CAP", f"{self.spend_micro + self._step_cost_micro} micro-USD > {self._cap_spend_micro}")
        if self.elapsed_s >= self.wall_cap_s:
            raise HardStop("WALL_CLOCK_CAP", f"{self.elapsed_s:.3f}s >= {self.wall_cap_s}s")

    def commit_step(self, step_tokens: int) -> None:
        self.steps += 1
        self.tokens += step_tokens
        self.spend_micro += self._step_cost_micro

    def usage(self) -> dict:
        return {"steps": self.steps, "tokens": self.tokens, "spend_micro_usd": self.spend_micro, "elapsed_s": round(self.elapsed_s, 6)}
