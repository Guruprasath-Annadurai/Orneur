"""
Phase 11 spec §78: normal read-only/simple actions that do not require
simulation must not instantiate heavy Simulation Chamber state.
"""
from __future__ import annotations

import ast
from pathlib import Path


def _imports_simulation(py_file: Path) -> bool:
    tree = ast.parse(py_file.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.startswith("orca.simulation") for alias in node.names):
                return True
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("orca.simulation"):
                return True
    return False


def test_cognitive_kernel_does_not_import_simulation():
    assert not _imports_simulation(Path("orca/cognitive/kernel.py"))


def test_truth_fabric_does_not_import_simulation():
    assert not _imports_simulation(Path("orca/truth/truth_fabric.py"))


def test_agent_runtime_does_not_import_simulation():
    """AgentRuntime stays simulation-agnostic -- wiring, if any, belongs
    to calling/orchestration code, never the runtime's own module."""
    assert not _imports_simulation(Path("orca/agent/runtime.py"))


def test_connectors_package_does_not_depend_on_simulation():
    for path in Path("orca/connectors").glob("*.py"):
        if path.name == "__init__.py":
            continue
        assert not _imports_simulation(path), f"{path} must not depend on orca.simulation"


def test_godmode_package_does_not_depend_on_simulation():
    """orca.godmode is the dependency direction's foundation --
    orca.simulation depends on it (godmode_integration.py), never the
    reverse."""
    for path in Path("orca/godmode").glob("*.py"):
        if path.name == "__init__.py":
            continue
        assert not _imports_simulation(path), f"{path} must not depend on orca.simulation"


def test_read_only_requirement_decision_has_zero_side_effects():
    """A NOT_REQUIRED decision for a read-only action touches no
    filesystem, no lease store, no connector state -- it is a pure
    function over its inputs."""
    from orca.agent.contracts import SideEffectClass
    from orca.simulation.contracts import ToolSimulationCapability
    from orca.simulation.requirement_policy import SimulationRequirementContext, decide_simulation_requirement

    ctx = SimulationRequirementContext(side_effect_class=SideEffectClass.READ_ONLY)
    result = decide_simulation_requirement(ctx, ToolSimulationCapability())
    assert result.value == "NOT_REQUIRED"


def test_single_action_chamber_never_imports_plan_or_branch_modules():
    """spec §52: a single-action static/read-only simulation must not
    pay multi-plan/branch orchestration overhead -- structurally, the
    single-action Chamber never even imports those modules."""
    import ast
    tree = ast.parse(Path("orca/simulation/chamber.py").read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
    assert "orca.simulation.plan_chamber" not in names
    assert "orca.simulation.branching" not in names
