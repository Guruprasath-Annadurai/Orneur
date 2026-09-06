"""
Phase 10 spec §65: normal-mode action without elevation should incur
minimal overhead. Proven structurally (fast path) and measured (see
orca/godmode/latency_bench.py for the numeric overhead).
"""
from __future__ import annotations

import ast
from pathlib import Path


def _imports_godmode(py_file: Path) -> bool:
    tree = ast.parse(py_file.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.startswith("orca.godmode") for alias in node.names):
                return True
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("orca.godmode"):
                return True
    return False


def test_cognitive_kernel_does_not_import_godmode():
    assert not _imports_godmode(Path("orca/cognitive/kernel.py"))


def test_truth_fabric_does_not_import_godmode():
    assert not _imports_godmode(Path("orca/truth/truth_fabric.py"))


def test_connectors_package_does_not_import_godmode():
    """Phase 9's connector fabric stays independently functional without
    Phase 10 -- godmode is an optional layer ON TOP, never a dependency
    of the base connector policy/registry/adapters."""
    for path in Path("orca/connectors").glob("*.py"):
        if path.name == "__init__.py":
            continue
        assert not _imports_godmode(path), f"{path} must not depend on orca.godmode"


def test_agent_runtime_without_lease_resolver_never_touches_godmode_module():
    """The default AgentRuntime(...) construction (no tenant_id, no
    lease_resolver -- every pre-Phase-10 caller) never imports
    orca.godmode at all: _try_elevate() is only ever called when
    lease_resolver is not None, and its own `from orca.godmode... import`
    statements are LOCAL to that method body, so the module is never even
    imported for a normal run.

    Deliberately does NOT delete already-imported `orca.godmode.*`
    entries from `sys.modules` (an earlier version of this test did, and
    that broke `tests/conftest.py`'s autouse monkeypatch isolation for
    every OTHER test running later in the same pytest session -- re-
    importing `orca.godmode.lease_store` after eviction creates a NEW
    module object with its `LEASE_DIR` back at the real, unpatched
    `ORCA_HOME` default, silently leaking real lease files into the
    developer's actual `~/.orca/godmode/leases/`. Instead this test
    snapshots the baseline set of already-loaded module names and asserts
    no NEW `orca.godmode.*` entry appears after the run -- a
    non-destructive check that catches the same regression without the
    side effect.)
    """
    import sys
    baseline = {m for m in sys.modules if m.startswith("orca.godmode")}

    from orca.agent.contracts import AgentAction, AgentGoal, AgentPlan, AgentTask, Capability, SideEffectClass, ToolSpec, ActionRiskLevel
    from orca.agent.runtime import AgentRuntime
    from orca.agent.tool_registry import AgentToolRegistry

    registry = AgentToolRegistry()
    spec = ToolSpec(tool_id="noop", description="noop", required_capabilities=frozenset({Capability.FILE_READ}), side_effect_class=SideEffectClass.READ_ONLY, risk_class=ActionRiskLevel.LOW)
    registry.register(spec, lambda **kw: "ok")
    goal = AgentGoal(objective="read", allowed_action_classes=frozenset({SideEffectClass.READ_ONLY}))
    task = AgentTask(description="read")
    action = AgentAction(task_id=task.task_id, tool_id="noop", expected_side_effect=SideEffectClass.READ_ONLY)
    plan = AgentPlan(tasks=[task], actions=[action])

    runtime = AgentRuntime(registry=registry, goal=goal, capabilities=frozenset({Capability.FILE_READ}))
    run, trace, world_state = runtime.execute(plan)

    after = {m for m in sys.modules if m.startswith("orca.godmode")}
    assert after == baseline, "a normal AgentRuntime run must never newly import any orca.godmode module"
