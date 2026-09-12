"""
Phase 17 section 32: traces the two limitations carried from Phase 16
(REQ-BOUNDARY-002c, REQ-COURT-ARCH-005) before declaring OCL integration
safe. See docs/orneur/phase-17/PHASE17_AUTHORITY_CALL_PATH.md for the full
narrative; these are the regression tests backing that document's claims.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
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


def test_ocl_package_does_not_import_orca_mission():
    """Extends Phase 16's INV-NATIVE-001 to the new orneur.intelligence.ocl
    package: no OCL module may gain a direct import path into Mission
    authority state."""
    ocl_dir = REPO_ROOT / "orneur" / "intelligence" / "ocl"
    offenders = []
    for py_file in ocl_dir.rglob("*.py"):
        if "orca.mission" in _imported_module_roots(py_file):
            offenders.append(str(py_file.relative_to(REPO_ROOT)))
    assert offenders == [], f"OCL module importing orca.mission (authority leak): {offenders}"


def test_no_model_facing_package_imports_orneur_intelligence_ocl_and_orca_mission_together():
    """No existing model-facing package imports BOTH ocl and orca.mission
    -- if one did, it would be a real candidate path for OCL content to
    reach Mission state and needs individual review, not a blanket check."""
    offenders = []
    for pkg in MODEL_FACING_PACKAGES:
        pkg_dir = REPO_ROOT / "orca" / pkg
        if not pkg_dir.is_dir():
            continue
        for py_file in pkg_dir.rglob("*.py"):
            roots = _imported_module_roots(py_file)
            if "orca.mission" in roots and "orneur.intelligence" in roots:
                offenders.append(str(py_file.relative_to(REPO_ROOT)))
    assert offenders == []


def test_arbiter_decide_has_zero_production_callers_today():
    """Honest finding, re-verified as a regression guard: `arbiter_decide()`
    (the only function that sets CourtVerdict.HUMAN_APPROVAL_REQUIRED) has
    no production call site anywhere in orca/ today -- only tests call it.
    This means there is currently no live path for `owner_approval_required`
    to be set from anything at all, model-influenced or otherwise: the
    function exists and is correctly deterministic in isolation, but is not
    yet wired into a real Mission/Relay approval flow. If a future PR adds
    a production caller, this test will start failing and MUST be revisited
    (the new caller needs its own owner_approval_required-source audit) --
    it must not simply be updated to keep passing."""
    production_callers = []
    for py_file in (REPO_ROOT / "orca").rglob("*.py"):
        if "cognitive_court.py" in str(py_file):
            continue  # the definition site itself, not a caller
        try:
            tree = ast.parse(py_file.read_text(), filename=str(py_file))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "arbiter_decide":
                production_callers.append(f"{py_file.relative_to(REPO_ROOT)}:{node.lineno}")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "arbiter_decide":
                production_callers.append(f"{py_file.relative_to(REPO_ROOT)}:{node.lineno}")

    assert production_callers == [], (
        f"New production caller(s) of arbiter_decide() found: {production_callers} -- "
        "trace how owner_approval_required is sourced there before treating this as safe."
    )
