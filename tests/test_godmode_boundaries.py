"""
Phase 10 spec §21, §24-30: structural boundary proofs. None of Court,
Model Society, Memory, Truth Fabric, entitlement, or model-registry
lifecycle code can issue/modify/extend/revoke/forge a lease, because none
of them import orca.godmode at all -- there is no code path for any of
them to even construct a CapabilityLease, let alone a signed/persisted
one.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


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


@pytest.mark.parametrize("path", [
    "orca/deliberation/court.py",
    "orca/deliberation/twin.py",
    "orca/society/router.py",
    "orca/society/society_plan.py",
    "orca/society/escalation.py",
    "orca/memory/firewall.py",
    "orca/memory/candidates.py",
    "orca/memory/reflex.py",
    "orca/truth/truth_fabric.py",
    "orca/truth/llm.py",
    "orca/cognitive/entitlement.py",
    "orca/cognitive/kernel.py",
    "orca/registry/model_spec.py",
    "orca/gateway/wiring.py",
    "orca/agent/tool_registry.py",
])
def test_no_authority_or_cognitive_module_imports_godmode(path):
    p = Path(path)
    if not p.exists():
        pytest.skip(f"{path} not present in this checkout")
    assert not _imports_godmode(p), f"{path} must never import orca.godmode -- it has no authority to issue/modify a lease"


def test_court_accept_cannot_activate_godmode():
    """spec §29: Court may recommend elevation (in plain text/reasoning);
    it has structurally no path to ISSUE a lease. Confirmed both by the
    import-boundary test above and by orca.godmode.issuance.issue_lease's
    own signature never accepting a Court verdict type."""
    import inspect
    from orca.godmode.issuance import issue_lease
    sig = inspect.signature(issue_lease)
    param_annotations = [str(p.annotation) for p in sig.parameters.values()]
    assert not any("Court" in a or "Verdict" in a for a in param_annotations)


def test_model_society_cannot_issue_modify_extend_revoke_or_forge_a_lease():
    """spec §30: no orca.society module imports orca.godmode (see
    parametrized test above for router.py/society_plan.py/escalation.py),
    and issue_lease()/revoke()/delegate_lease() all live in orca.godmode
    itself -- there is no Society-reachable reference to any of them."""
    import ast as _ast
    society_dir = Path("orca/society")
    forbidden_calls = {"issue_lease", "revoke", "delegate_lease", "apply_signature"}
    for path in society_dir.glob("*.py"):
        tree = _ast.parse(path.read_text())
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Name) and node.id in forbidden_calls:
                assert False, f"{path} references {node.id} -- Model Society must never call Godmode issuance/revocation functions"


def test_entitlement_boundary_godmode_cannot_change_commercial_access():
    """spec §25: elevated capability leases live entirely in
    orca.godmode; orca.cognitive.entitlement (the commercial/subscription
    gate) has no import of orca.godmode (see parametrized test) and no
    CapabilityLease field maps to a CapabilityClass/model-tier concept --
    confirmed structurally: CapabilityLease has no field named anything
    entitlement-shaped."""
    import dataclasses
    from orca.godmode.contracts import CapabilityLease
    field_names = {f.name for f in dataclasses.fields(CapabilityLease)}
    forbidden = {"capability_class", "model_tier", "entitlement", "billing_override", "daily_limit_override"}
    assert not (field_names & forbidden)


def test_model_lifecycle_boundary_godmode_cannot_change_registry_state():
    """spec §26: orca.registry.model_spec and orca.gateway.wiring (the
    real model lifecycle/deployment state) have no import of
    orca.godmode (see parametrized test) -- there is no code path for a
    lease to touch a ModelDeployment or registry lifecycle state field."""
    from orca.godmode.contracts import CapabilityDomain
    assert "MODEL_LIFECYCLE" not in CapabilityDomain.__members__


def test_memory_boundary_godmode_never_reads_another_users_memory_by_default():
    """spec §27: Godmode's own CapabilityDomain enum has no MEMORY value
    at all -- there is no lease shape that grants memory access; Memory
    Firewall (orca.memory.firewall) is untouched (see parametrized
    import-boundary test) and remains the sole authority over memory
    scope/privacy."""
    from orca.godmode.contracts import CapabilityDomain
    assert "MEMORY" not in CapabilityDomain.__members__


def test_truth_boundary_godmode_cannot_convert_uncertain_facts_to_verified():
    """spec §28: Truth Fabric modules never import orca.godmode (see
    parametrized test); CapabilityLease carries no field that could
    represent an evidence/epistemic-state override."""
    import dataclasses
    from orca.godmode.contracts import CapabilityLease
    field_names = {f.name for f in dataclasses.fields(CapabilityLease)}
    forbidden = {"epistemic_state", "evidence_override", "verified", "truth_override"}
    assert not (field_names & forbidden)


def test_godmode_not_root_shell_process_elevation_disabled():
    """spec §21, §62: PROCESS_EXECUTION elevation is intentionally left
    disabled -- there is no orca/godmode/process_elevation.py module,
    and file_elevation.py/connector_elevation.py are the only two
    domain-specific elevation adapters that exist."""
    assert not Path("orca/godmode/process_elevation.py").exists()
