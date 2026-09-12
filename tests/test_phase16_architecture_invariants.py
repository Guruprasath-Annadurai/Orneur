"""
Phase 16 architecture invariants (INV-NATIVE-001, INV-NATIVE-002).

These are real dependency-boundary tests, not constant assertions: they parse
the actual source of the intelligence-adjacent packages and prove the
"authority flows downward only through deterministic mechanisms" property
that PHASE16_CANONICAL_ARCHITECTURE.md documents. If a future change adds an
`orca.mission` import to routing/agent/training code, or wires Court verdicts
directly into `orca/agent/policy.py`'s authorization path, these tests fail.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_FACING_PACKAGES = ["agent", "society", "train", "cognitive", "deliberation", "gateway"]


def _imported_module_roots(py_file: Path) -> set[str]:
    tree = ast.parse(py_file.read_text(), filename=str(py_file))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0] + "." + alias.name.split(".")[1] if "." in alias.name else alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            parts = node.module.split(".")
            roots.add(".".join(parts[:2]) if len(parts) > 1 else parts[0])
    return roots


def test_no_model_facing_package_imports_orca_mission():
    """INV-NATIVE-001: model/routing/agent/training code must never be able to
    mutate Mission state directly -- only the Mission engine's own callers
    (Relay/API layer) may. A model that could touch Mission state could
    manufacture its own execution authority."""
    offenders = []
    for pkg in MODEL_FACING_PACKAGES:
        pkg_dir = REPO_ROOT / "orca" / pkg
        if not pkg_dir.is_dir():
            continue
        for py_file in pkg_dir.rglob("*.py"):
            if "orca.mission" in _imported_module_roots(py_file):
                offenders.append(str(py_file.relative_to(REPO_ROOT)))
    assert offenders == [], f"Model-facing code importing orca.mission (authority leak): {offenders}"


def test_agent_policy_does_not_import_deliberation():
    """INV-NATIVE-002: orca/agent/policy.py's own docstring states it is "the
    ONLY thing that may authorize" elevated actions. Court verdicts
    (orca.deliberation) must remain data consumed elsewhere, never a second,
    implicit authorization path wired into the actual authorizer."""
    policy_file = REPO_ROOT / "orca" / "agent" / "policy.py"
    assert policy_file.is_file()
    assert "orca.deliberation" not in _imported_module_roots(policy_file)
