"""Shared helpers for the Workstream G (training-prep) tests. Test-only; never imported by production code. Everything is synthetic."""
from __future__ import annotations

from pathlib import Path

from orca.train.dryrun.binding import Binding
from orca.train.dryrun.budget import ResourceBudget
from orca.train.dryrun.harness import run_core
from orca.train.dryrun.toy import Plan

BIND = Binding("a" * 40, True, "b" * 64, ("c" * 64,), None)
ENVSHA = "d" * 64


def big_budget(**over) -> ResourceBudget:
    kw = dict(max_steps=1000, max_tokens=10**9, max_wall_clock_s=10**6, max_spend_usd=1000.0, sim_cost_usd_per_step=0.01)
    kw.update(over)
    return ResourceBudget(**kw)


def run(plan: Plan, root, *, run_id: str = "run-1", budget: ResourceBudget | None = None, **kw):
    kw.setdefault("binding", BIND)
    kw.setdefault("env_manifest_sha256", ENVSHA)
    return run_core(plan, Path(root), run_id=run_id, budget=budget or big_budget(), **kw)


def ckpt_bytes(root, step: int) -> dict:
    d = Path(root) / "checkpoints" / f"ckpt-{step:06d}"
    return {p.name: p.read_bytes() for p in sorted(d.iterdir())}
