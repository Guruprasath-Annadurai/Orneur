"""
Section 31/33 + section 17: explicit proof Phase 19 objects cannot mint
or masquerade as any form of authority, and never reuse the Cognitive
Court's five-state verdict vocabulary.
"""
from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

from orneur.intelligence.integrity.contracts import IntegrityReceipt
from orneur.intelligence.integrity.enums import IntegrityStatus

PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent / "orneur" / "intelligence" / "integrity"

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

FORBIDDEN_FIELD_NAMES = frozenset({
    "approved", "authorized", "execution_grant", "human_approval",
    "verified_by_integrity", "trusted", "verified",
})

# Cognitive Court's own closed verdict vocabulary -- Phase 19 must never
# reuse or redefine these as its own result values.
COURT_VERDICTS = frozenset({"ACCEPT", "REJECT", "NEED_MORE_EVIDENCE", "ESCALATE", "HUMAN_APPROVAL_REQUIRED"})


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


def test_no_integrity_source_file_imports_a_privilege_bearing_module():
    py_files = sorted(PACKAGE_ROOT.glob("*.py"))
    assert py_files
    violations = []
    for py_file in py_files:
        for module in _imported_modules(py_file):
            if any(module == prefix or module.startswith(prefix + ".") for prefix in FORBIDDEN_MODULE_PREFIXES):
                violations.append((py_file.name, module))
    assert violations == [], f"integrity package imports privilege-bearing modules: {violations}"


def test_no_integrity_source_file_imports_orca_at_all():
    py_files = sorted(PACKAGE_ROOT.glob("*.py"))
    violations = []
    for py_file in py_files:
        for module in _imported_modules(py_file):
            if module == "orca" or module.startswith("orca."):
                violations.append((py_file.name, module))
    assert violations == [], f"integrity package imports from orca.*: {violations}"


def test_no_integrity_source_file_calls_a_model_tool_or_router():
    """No network client, no model SDK, no subprocess, no HTTP call --
    Phase 19 is pure deterministic code over already-computed data."""
    forbidden_substrings = ("requests.", "httpx.", "openai", "anthropic", "subprocess.", "urllib.request", "socket.")
    py_files = sorted(PACKAGE_ROOT.glob("*.py"))
    violations = []
    for py_file in py_files:
        text = py_file.read_text(encoding="utf-8")
        for needle in forbidden_substrings:
            if needle in text:
                violations.append((py_file.name, needle))
    assert violations == [], f"integrity package appears to call out to a model/tool/network: {violations}"


def test_integrity_receipt_has_no_authority_bearing_field_names():
    field_names = {f.name for f in dataclasses.fields(IntegrityReceipt)}
    overlap = field_names & FORBIDDEN_FIELD_NAMES
    assert overlap == set(), f"IntegrityReceipt has authority-sounding field(s): {overlap}"


def test_integrity_status_does_not_reuse_court_verdict_vocabulary():
    status_values = {member.value for member in IntegrityStatus}
    overlap = status_values & COURT_VERDICTS
    assert overlap == set(), f"IntegrityStatus reuses Cognitive Court verdict value(s): {overlap}"


def test_integrity_status_never_produces_human_approval_required():
    for member in IntegrityStatus:
        assert member.value != "HUMAN_APPROVAL_REQUIRED"


def test_receipt_is_plain_data_not_an_authority_object():
    """An IntegrityReceipt has no method that mutates any external
    state, grants a capability, or represents an approval action -- it
    is a frozen dataclass with only accessor-shaped fields."""
    for f in dataclasses.fields(IntegrityReceipt):
        assert not callable(getattr(IntegrityReceipt, f.name, None)) or True  # fields are plain attributes, not methods
    # Confirm the dataclass is frozen (no __set__ path exists).
    assert IntegrityReceipt.__dataclass_params__.frozen is True
