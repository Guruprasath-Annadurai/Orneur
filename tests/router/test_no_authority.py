"""
Section 31/33 + section 17 + section 18: explicit proof Phase 20
objects cannot mint or masquerade as any form of authority, never reuse
the Cognitive Court's five-state verdict vocabulary, imports no orca.*
module, calls no model/tool/network, and -- the most safety-critical
regression in this closure -- never internally computes
`expected = digest(incoming_overlay)` from the overlay it is evaluating
(the exact forged-overlay anti-pattern Phase 19 closed).
"""
from __future__ import annotations

import ast
import dataclasses
import re
from pathlib import Path

from orneur.intelligence.router.contracts import RoutingDecision
from orneur.intelligence.router.enums import RoutingStatus

PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent / "orneur" / "intelligence" / "router"

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
    "orca.society.router",
)

FORBIDDEN_FIELD_NAMES = frozenset({
    "approved", "authorized", "execution_grant", "human_approval",
    "verified_by_integrity", "trusted", "verified", "permission_grant",
})

# Cognitive Court's own closed verdict vocabulary -- Phase 20 must never
# reuse or redefine these as its own status/reason values.
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


def test_no_router_source_file_imports_a_privilege_bearing_module():
    py_files = sorted(PACKAGE_ROOT.glob("*.py"))
    assert py_files
    violations = []
    for py_file in py_files:
        for module in _imported_modules(py_file):
            if any(module == prefix or module.startswith(prefix + ".") for prefix in FORBIDDEN_MODULE_PREFIXES):
                violations.append((py_file.name, module))
    assert violations == [], f"router package imports privilege-bearing modules: {violations}"


def test_no_router_source_file_imports_orca_at_all():
    py_files = sorted(PACKAGE_ROOT.glob("*.py"))
    violations = []
    for py_file in py_files:
        for module in _imported_modules(py_file):
            if module == "orca" or module.startswith("orca."):
                violations.append((py_file.name, module))
    assert violations == [], f"router package imports from orca.*: {violations}"


def test_no_router_source_file_calls_a_model_tool_or_network():
    forbidden_substrings = ("requests.", "httpx.", "openai", "anthropic", "subprocess.", "urllib.request", "socket.")
    py_files = sorted(PACKAGE_ROOT.glob("*.py"))
    violations = []
    for py_file in py_files:
        text = py_file.read_text(encoding="utf-8")
        for needle in forbidden_substrings:
            if needle in text:
                violations.append((py_file.name, needle))
    assert violations == [], f"router package appears to call out to a model/tool/network: {violations}"


def test_routing_decision_has_no_authority_bearing_field_names():
    field_names = {f.name for f in dataclasses.fields(RoutingDecision)}
    overlap = field_names & FORBIDDEN_FIELD_NAMES
    assert overlap == set(), f"RoutingDecision has authority-sounding field(s): {overlap}"


def test_routing_status_does_not_reuse_court_verdict_vocabulary():
    status_values = {member.value for member in RoutingStatus}
    overlap = status_values & COURT_VERDICTS
    assert overlap == set(), f"RoutingStatus reuses Cognitive Court verdict value(s): {overlap}"


def test_routing_decision_is_frozen_plain_data():
    assert RoutingDecision.__dataclass_params__.frozen is True


def test_no_router_source_file_reimplements_digest_of_incoming_overlay():
    """THE explicit regression named by the Phase 20 spec (section 18):
    the router must never compute `expected = digest(overlay)` (or any
    equivalent self-referential digest-of-the-input-being-verified)
    internally -- that reintroduces the exact forged-overlay defect
    Phase 19 closed. evaluator.py must obtain its overlay digest ONLY
    via the return value of overlay_trust.verify_trusted_overlay(),
    never by calling a canonical/digest function directly on the
    `overlay` parameter it received."""
    evaluator_path = PACKAGE_ROOT / "evaluator.py"
    text = evaluator_path.read_text(encoding="utf-8")

    # No direct call to any *.digest(overlay)/*.canonical.digest(overlay)
    # pattern anywhere in the router package.
    forbidden_pattern = re.compile(r"digest\s*\(\s*overlay\b")
    py_files = sorted(PACKAGE_ROOT.glob("*.py"))
    violations = []
    for py_file in py_files:
        file_text = py_file.read_text(encoding="utf-8")
        for match in forbidden_pattern.finditer(file_text):
            violations.append((py_file.name, match.group(0)))
    assert violations == [], f"router package appears to compute digest(overlay) directly: {violations}"

    # And the evaluator's overlay digest must come from the reused
    # Phase-19 trust seam's return value, not a locally-imported
    # canonicalization module.
    assert "overlay_trust.verify_trusted_overlay(" in text
    assert "epistemic_canonical" not in text
    assert "epistemic.canonical" not in text


def test_router_evaluator_reuses_the_phase19_overlay_trust_seam():
    """Confirms the router imports and calls the SAME function Phase 19
    uses internally, rather than duplicating security-sensitive digest
    comparison logic."""
    evaluator_path = PACKAGE_ROOT / "evaluator.py"
    text = evaluator_path.read_text(encoding="utf-8")
    assert "from orneur.intelligence.integrity import overlay_trust" in text
    assert "verify_trusted_overlay" in text
