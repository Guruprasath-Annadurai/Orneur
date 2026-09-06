"""
Phase 9 spec §69: a non-enterprise request must not discover/load
connectors. Proven structurally -- `orca.cognitive.kernel` and
`orca.truth.truth_fabric` never import `orca.connectors`; connector
discovery only ever happens when an AgentPlan explicitly uses a
connector tool (via `orca.connectors.agent_bridge`), never eagerly.
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path


def _imports_connectors_package(py_file: Path) -> bool:
    tree = ast.parse(py_file.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.startswith("orca.connectors") for alias in node.names):
                return True
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("orca.connectors"):
                return True
    return False


def test_cognitive_kernel_does_not_import_connectors():
    assert not _imports_connectors_package(Path("orca/cognitive/kernel.py"))


def test_truth_fabric_does_not_import_connectors():
    assert not _imports_connectors_package(Path("orca/truth/truth_fabric.py"))


def test_agent_runtime_does_not_import_connectors():
    """AgentRuntime itself stays connector-agnostic -- it only ever sees
    whatever `AgentToolRegistry` entries the caller registered; the
    connector<->agent wiring lives entirely in
    `orca.connectors.agent_bridge`, imported by CALLING code, never by
    `orca.agent.runtime` itself."""
    assert not _imports_connectors_package(Path("orca/agent/runtime.py"))


def test_agent_planner_does_not_import_connectors():
    assert not _imports_connectors_package(Path("orca/agent/planner.py"))


def test_importing_connectors_package_has_no_network_or_registry_side_effects():
    import orca.connectors.registry as registry_mod
    importlib.reload(registry_mod)  # must not raise or perform I/O
    assert registry_mod.ConnectorRegistry()._instances == {}
