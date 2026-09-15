"""
Section 57: no code path in orneur.intelligence.epistemic may import
anything from the execution-grant / policy-authorization / Court-mutation
/ human-approval-mutation systems. Epistemic overlays are DATA; Phase 18
must not become a second, quieter authority channel.
"""
from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_MODULE_PREFIXES = (
    "orca.deliberation.court",
    "orca.mission.cognitive_court",
    "orca.mission.court_mission_gate",
    "orca.mission.authority_bridge",
    "orca.godmode.authority_ledger",
    "orca.godmode.policy",
    "orca.agent.policy",
    "orca.agent.court_hook",
    "orca.simulation.court_hook",
    "orca.cognitive.policy",
    "orca.connectors.policy",
)

PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent / "orneur" / "intelligence" / "epistemic"


def _imported_modules(py_file: Path) -> set[str]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_no_epistemic_source_file_imports_a_privilege_bearing_module():
    py_files = sorted(PACKAGE_ROOT.glob("*.py"))
    assert py_files, "expected the epistemic package to contain source files"

    violations = []
    for py_file in py_files:
        for module in _imported_modules(py_file):
            if any(module == prefix or module.startswith(prefix + ".") for prefix in FORBIDDEN_MODULE_PREFIXES):
                violations.append((py_file.name, module))

    assert violations == [], f"epistemic package imports privilege-bearing modules: {violations}"


def test_no_epistemic_source_file_imports_orca_at_all():
    """Stronger, simpler invariant: the whole Phase 18 package only ever
    needs orneur.intelligence.ocl -- it should never need to reach into
    the legacy orca.* namespace (where Court/policy/authority live) at
    all."""
    py_files = sorted(PACKAGE_ROOT.glob("*.py"))
    violations = []
    for py_file in py_files:
        for module in _imported_modules(py_file):
            if module == "orca" or module.startswith("orca."):
                violations.append((py_file.name, module))
    assert violations == [], f"epistemic package imports from orca.*: {violations}"
