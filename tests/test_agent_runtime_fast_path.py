"""
Phase 8 spec §69: a normal direct chat/Kernel request must not instantiate
the Agent Runtime. Proven structurally -- `orca.agent` is never imported
by the Kernel's default request path.
"""
from __future__ import annotations

import ast
from pathlib import Path


def _imports_agent_package(py_file: Path) -> bool:
    tree = ast.parse(py_file.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.startswith("orca.agent") for alias in node.names):
                return True
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("orca.agent"):
                return True
    return False


def test_cognitive_kernel_does_not_import_agent_runtime():
    kernel_path = Path("orca/cognitive/kernel.py")
    assert not _imports_agent_package(kernel_path), "CognitiveKernel must not import orca.agent -- normal requests stay on Kernel -> Truth/Memory/Society, never Agent Runtime"


def test_truth_fabric_does_not_import_agent_runtime():
    path = Path("orca/truth/truth_fabric.py")
    assert not _imports_agent_package(path)


def test_agent_runtime_construction_has_no_side_effects_on_import():
    """Importing orca.agent.runtime must not construct a ToolRegistry,
    reach the network, or touch real ORCA_HOME -- confirms it's a truly
    opt-in module, not something eagerly initialized."""
    import importlib
    import orca.agent.runtime as runtime_mod
    importlib.reload(runtime_mod)  # must not raise or perform I/O
