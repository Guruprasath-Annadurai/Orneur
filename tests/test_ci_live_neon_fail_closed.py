"""
Phase 15.11.2 -- structural/static tests proving the
`.github/workflows/phase14b-distributed-qualification.yml` fail-closed
guard actually covers every Phase 15 live-Neon dispatch mode, and is
ordered BEFORE the mode-specific pytest steps.

Motivation (spec item 2/3): run `34350468007` was green
(`conclusion: success`) even though its Relay live-Neon step showed
`22 passed, 34 skipped` -- ALL 34 real live-Neon tests silently
skipped because `ORNEUR_MISSION_DATABASE_URL`/`_DIRECT` were empty. A
green workflow with all live tests skipped is not a live
qualification. These tests fail if a future edit re-opens that hole:
adding a new step that reads `ORNEUR_MISSION_DATABASE_URL` from
`secrets` without adding its mode to the preflight's `case` statement,
or reordering the preflight after any such step, breaks
`test_every_live_neon_mode_is_covered_by_the_preflight_guard` or
`test_preflight_guard_runs_before_every_live_neon_step` respectively.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

_WORKFLOW_PATH = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "phase14b-distributed-qualification.yml"
_PREFLIGHT_NAME_SUBSTRING = "Fail closed if a Phase 15 live-Neon mode is selected without mission DB secrets"

_MODE_CONDITION_RE = re.compile(r"github\.event\.inputs\.fresh_runner_mode == '([^']+)'")


def _load_workflow() -> dict:
    return yaml.safe_load(_WORKFLOW_PATH.read_text())


def _qualify_steps() -> list[dict]:
    data = _load_workflow()
    return data["jobs"]["qualify"]["steps"]


def _step_modes(step: dict) -> list[str]:
    """Every `fresh_runner_mode == '...'` literal referenced by this
    step's own `if:` condition (a step may only ever gate on exactly
    one mode in this workflow, but this returns however many are
    found, defensively)."""
    condition = step.get("if", "")
    return _MODE_CONDITION_RE.findall(condition)


def _steps_using_mission_db_secret() -> list[dict]:
    """Every MODE-SPECIFIC step (excluding the preflight guard itself)
    whose `env` block wires up `secrets.ORNEUR_MISSION_DATABASE_URL` --
    these are exactly the steps a future editor might add without
    remembering the preflight guard."""
    out = []
    for step in _qualify_steps():
        if _PREFLIGHT_NAME_SUBSTRING in (step.get("name") or ""):
            continue
        env = step.get("env") or {}
        if any("ORNEUR_MISSION_DATABASE_URL" in str(v) for v in env.values()) or "ORNEUR_MISSION_DATABASE_URL" in env:
            out.append(step)
    return out


def _find_preflight_step_index() -> int:
    steps = _qualify_steps()
    for i, step in enumerate(steps):
        if _PREFLIGHT_NAME_SUBSTRING in (step.get("name") or ""):
            return i
    raise AssertionError(f"No preflight step found containing {_PREFLIGHT_NAME_SUBSTRING!r}")


def test_preflight_step_exists_and_has_no_mode_restricting_if():
    """The preflight must run on EVERY dispatch (so it can inspect
    whichever mode was actually selected), not be itself gated behind
    one specific mode."""
    steps = _qualify_steps()
    idx = _find_preflight_step_index()
    preflight = steps[idx]
    assert "if" not in preflight, "the preflight step must not be gated behind a single mode's `if:` condition"


def test_preflight_checks_both_pooled_and_direct_variables():
    steps = _qualify_steps()
    preflight = steps[_find_preflight_step_index()]
    run_script = preflight["run"]
    assert "ORNEUR_MISSION_DATABASE_URL" in run_script
    assert "ORNEUR_MISSION_DATABASE_URL_DIRECT" in run_script
    env = preflight.get("env", {})
    assert "ORNEUR_MISSION_DATABASE_URL" in env
    assert "ORNEUR_MISSION_DATABASE_URL_DIRECT" in env


def test_every_live_neon_mode_is_covered_by_the_preflight_guard():
    """For every step that actually wires up the mission DB secret,
    its gating mode(s) must appear as a literal token in the
    preflight's own `run` script (its `case ... in` pattern). This is
    the test that fails if a future live-Neon mode is added without
    updating the guard."""
    steps = _qualify_steps()
    preflight = steps[_find_preflight_step_index()]
    guard_script = preflight["run"]

    modes_requiring_guard: set[str] = set()
    for step in _steps_using_mission_db_secret():
        modes_requiring_guard.update(_step_modes(step))

    assert modes_requiring_guard, "expected at least one live-Neon mode to be discovered from the workflow"
    for mode in modes_requiring_guard:
        assert mode in guard_script, (
            f"mode {mode!r} reads ORNEUR_MISSION_DATABASE_URL but is NOT covered by the "
            f"preflight guard's case statement -- this is exactly the gap that let run "
            f"34350468007 go green with 34 silently-skipped live tests."
        )


def test_preflight_guard_runs_before_every_live_neon_step():
    steps = _qualify_steps()
    preflight_idx = _find_preflight_step_index()
    for step in _steps_using_mission_db_secret():
        step_idx = steps.index(step)
        assert preflight_idx < step_idx, (
            f"step {step.get('name')!r} (index {step_idx}) uses the mission DB secret but runs "
            f"BEFORE the preflight guard (index {preflight_idx}) -- the guard must execute first."
        )


def test_focused_relay_workflow_preflight_exists_before_pytest_steps():
    """Phase 15.12 item 26: the focused, Northflank-free
    `phase15-relay-security-qualification.yml` workflow must ALSO
    fail closed on missing mission DB secrets, ordered before its own
    pytest steps -- preserving the 15.11.2 invariant in the new,
    cleaner qualification path."""
    focused_path = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "phase15-relay-security-qualification.yml"
    data = yaml.safe_load(focused_path.read_text())
    steps = data["jobs"]["qualify"]["steps"]

    preflight_idx = next(
        (i for i, s in enumerate(steps) if "Fail closed if mission DB secrets are missing" in (s.get("name") or "")),
        None,
    )
    assert preflight_idx is not None, "focused workflow must have its own fail-closed preflight step"

    preflight = steps[preflight_idx]
    assert "if" not in preflight
    assert "ORNEUR_MISSION_DATABASE_URL" in preflight["run"]
    assert "ORNEUR_MISSION_DATABASE_URL_DIRECT" in preflight["run"]

    for i, step in enumerate(steps):
        env = step.get("env") or {}
        if i == preflight_idx:
            continue
        if "ORNEUR_MISSION_DATABASE_URL" in env:
            assert preflight_idx < i, f"step {step.get('name')!r} runs before the focused workflow's own preflight"


def test_focused_relay_workflow_has_no_northflank_step():
    """The whole point of the focused workflow (item 26) -- it must
    never actually RUN a Northflank login/deploy step that could make
    a genuinely successful Relay qualification report a failed whole-
    job conclusion for an unrelated reason (the exact ambiguity
    discovered in run 34385145178). Checks the actual step `run`/`env`
    bodies, not the file's own prose explaining why there isn't one."""
    focused_path = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "phase15-relay-security-qualification.yml"
    data = yaml.safe_load(focused_path.read_text())
    for step in data["jobs"]["qualify"]["steps"]:
        run_script = step.get("run", "")
        env = step.get("env") or {}
        assert "northflank" not in run_script.lower()
        assert "NORTHFLANK_API_TOKEN" not in env
        assert "NORTHFLANK_API_TOKEN" not in str(step.get("uses", ""))


def test_workflow_dispatch_options_include_every_gated_mode():
    """Sanity cross-check: every mode gating a mission-DB-secret step
    must also be a real, declared `workflow_dispatch` choice (a typo'd
    mode name in a step's `if:` would otherwise be gated by a guard
    entry that can never actually be selected)."""
    data = _load_workflow()
    # PyYAML (1.1 resolver) parses the bare top-level `on:` key as the
    # boolean True, not the string "on" -- look it up either way so
    # this test survives a loader-behavior difference.
    on_block = data.get("on", data.get(True))
    declared_options = set(on_block["workflow_dispatch"]["inputs"]["fresh_runner_mode"]["options"])
    for step in _steps_using_mission_db_secret():
        for mode in _step_modes(step):
            assert mode in declared_options, f"mode {mode!r} is not a declared workflow_dispatch option"
