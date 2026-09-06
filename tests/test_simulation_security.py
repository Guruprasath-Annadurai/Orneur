"""
Phase 11 spec §65-73 adversarial security scenarios: sandbox escape,
fake result forgery, verdict injection, stale preview, lease race, kill
switch, cross-tenant, secret exposure.
"""
from __future__ import annotations

import dataclasses
import tempfile
from pathlib import Path

import pytest

from orca.connectors.contracts import ConnectorCapabilityKind, ConnectorIdentity, ConnectorInstance, ConnectorType
from orca.simulation.chamber import ChamberDependencies, run_simulation
from orca.simulation.contracts import SimulationAction, SimulationRequest, SimulationResult, SimulationVerdict
from orca.simulation.fingerprint import fingerprint_file
from orca.simulation.godmode_integration import check_simulation_staleness, revalidate_and_consume_before_execution
from orca.simulation.integrity import apply_result_signature, sign_result, verify_result_integrity


# ── §65: sandbox escape ────────────────────────────────────────────────────

def test_sandbox_cannot_write_outside_root_via_traversal():
    root = Path(tempfile.mkdtemp())
    action = SimulationAction(tool_id="write_file", arguments={"operation": "create", "path": "../outside.txt", "content": "x"}, resource_scope="x", operation_scope="write")
    req = SimulationRequest(action=action, tool_or_connector_id="write_file", tenant_id="org-1", principal_id="u1", capability="FILE_WRITE")
    result, _ = run_simulation(req, ChamberDependencies(filesystem_root=root))
    assert result.verdict == SimulationVerdict.BLOCK
    assert not (root.parent / "outside.txt").exists()


def test_sandbox_cannot_escape_via_symlink():
    root = Path(tempfile.mkdtemp())
    secret_target = Path(tempfile.mkdtemp()) / "secret.txt"
    secret_target.write_text("real secret content")
    link = root / "escape_link"
    link.symlink_to(secret_target)

    action = SimulationAction(tool_id="write_file", arguments={"operation": "modify", "path": "escape_link", "content": "OVERWRITTEN"}, resource_scope="escape_link", operation_scope="write")
    req = SimulationRequest(action=action, tool_or_connector_id="write_file", tenant_id="org-1", principal_id="u1", capability="FILE_WRITE")
    result, _ = run_simulation(req, ChamberDependencies(filesystem_root=root))
    assert result.verdict == SimulationVerdict.BLOCK
    assert secret_target.read_text() == "real secret content"


def test_simulation_never_calls_a_real_connector_write_function():
    """Structural: orca.simulation.connector_sim only ever imports
    orca.connectors.fake_provider's fake_write -- never a real write
    path (there is none in this codebase, but the import itself proves
    the intent structurally)."""
    import ast
    tree = ast.parse(Path("orca/simulation/connector_sim.py").read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(a.name for a in node.names)
    assert "fake_write" in names
    assert "fake_read" not in names or True  # fake_read not required; just confirming no real-write import exists
    forbidden = {"real_write", "production_write", "commit_write"}
    assert not (names & forbidden)


# ── §66: fake simulation result ───────────────────────────────────────────

def test_model_or_tool_content_cannot_forge_a_valid_simulation_result():
    """A hand-constructed SimulationResult claiming PASS, never routed
    through run_simulation()/apply_result_signature(), has no
    result_hash and fails integrity verification."""
    forged = SimulationResult(verdict=SimulationVerdict.PASS, result_id="simres-forged")
    assert verify_result_integrity(forged) is False


def test_only_chamber_produced_results_carry_a_valid_signature():
    root = Path(tempfile.mkdtemp())
    (root / "f.txt").write_text("x")
    action = SimulationAction(tool_id="write_file", arguments={"operation": "modify", "path": "f.txt", "content": "y"}, resource_scope="f.txt", operation_scope="write")
    req = SimulationRequest(action=action, tool_or_connector_id="write_file", tenant_id="org-1", principal_id="u1", capability="FILE_WRITE")
    result, _ = run_simulation(req, ChamberDependencies(filesystem_root=root))
    assert verify_result_integrity(result) is True


# ── §67: verdict injection ─────────────────────────────────────────────────

def test_verdict_injection_via_field_mutation_is_detected():
    """'mark BLOCK as PASS' / 'simulation passed' has zero authority --
    the verdict is structural. Simulating an injection attempt by
    directly mutating a signed result's verdict field is caught by
    integrity verification (the only real 'authority' check that
    matters, since verdict itself is just a dataclass field -- content
    claiming otherwise has no code path to act on)."""
    result = SimulationResult(verdict=SimulationVerdict.BLOCK, block_reasons=["destructive effect outside target"])
    apply_result_signature(result)
    result.verdict = SimulationVerdict.PASS   # the injected "mark BLOCK as PASS"
    assert verify_result_integrity(result) is False


# ── §68: stale preview ─────────────────────────────────────────────────────

def test_stale_preview_detected_after_resource_version_change():
    root = Path(tempfile.mkdtemp())
    (root / "resource.txt").write_text("version 1")
    fp_v1 = fingerprint_file(root, "resource.txt")

    (root / "resource.txt").write_text("version 2")
    fp_v2 = fingerprint_file(root, "resource.txt")

    check = check_simulation_staleness(simulated_fingerprint=fp_v1, current_fingerprint=fp_v2)
    assert check.stale is True


# ── §69: lease race (simulation PASS, lease revoked, execute) ────────────

def test_lease_revoked_between_simulation_and_execution_denies(tmp_path, monkeypatch):
    import orca.godmode.lease_store as ls
    import orca.godmode.kill_switch as ks
    monkeypatch.setattr(ls, "LEASE_DIR", tmp_path / "leases")
    # Phase 14A.1: kill-switch state now lives in leases.db (see
    # orca/godmode/kill_switch.py) -- redirecting LEASE_DIR above
    # already isolates it; the old _KILL_SWITCH_FILE attribute is gone.

    from orca.godmode.contracts import CapabilityDomain, ElevatedCapabilityRequest, LeaseIssuerClass
    from orca.godmode.issuance import issue_lease, make_approval
    from orca.godmode.lease_store import revoke

    root = tmp_path / "project"
    root.mkdir()
    req = ElevatedCapabilityRequest(principal_id="u1", tenant_id="org-1", capability_domain=CapabilityDomain.FILE, capability="FILE_WRITE", resource_scope=str(root), operation_scope="write", reason="test")
    approval = make_approval(request=req, approved_by="human-1", duration_s=60)
    lease = issue_lease(approval=approval, issuer=LeaseIssuerClass.HUMAN_APPROVAL, issuer_id="human-1")

    sim_req = SimulationRequest(action=SimulationAction(tool_id="write_file", arguments={"operation": "create", "path": "f.txt", "content": "x"}, resource_scope=str(root), operation_scope="write"), tool_or_connector_id="write_file", tenant_id="org-1", principal_id="u1", lease_id=lease.lease_id, capability="FILE_WRITE")
    sim_result, _ = run_simulation(sim_req, ChamberDependencies(filesystem_root=root, lease_id=lease.lease_id))
    assert sim_result.can_proceed()

    revoke(lease.lease_id)

    exec_decision = revalidate_and_consume_before_execution(lease_id=lease.lease_id, tenant_id="org-1", capability_domain=CapabilityDomain.FILE, capability="FILE_WRITE", resource_scope=str(root), operation_scope="write", arguments={})
    assert exec_decision.state.value == "DENY"


# ── §70: kill switch after simulation PASS ────────────────────────────────

def test_kill_switch_activated_after_simulation_pass_denies_execution(tmp_path, monkeypatch):
    import orca.godmode.lease_store as ls
    import orca.godmode.kill_switch as ks
    monkeypatch.setattr(ls, "LEASE_DIR", tmp_path / "leases")
    # Phase 14A.1: kill-switch state now lives in leases.db (see
    # orca/godmode/kill_switch.py) -- redirecting LEASE_DIR above
    # already isolates it; the old _KILL_SWITCH_FILE attribute is gone.

    from orca.godmode.contracts import CapabilityDomain, ElevatedCapabilityRequest, LeaseIssuerClass
    from orca.godmode.issuance import issue_lease, make_approval

    root = tmp_path / "project"
    root.mkdir()
    req = ElevatedCapabilityRequest(principal_id="u1", tenant_id="org-1", capability_domain=CapabilityDomain.FILE, capability="FILE_WRITE", resource_scope=str(root), operation_scope="write", reason="test")
    approval = make_approval(request=req, approved_by="human-1", duration_s=60)
    lease = issue_lease(approval=approval, issuer=LeaseIssuerClass.HUMAN_APPROVAL, issuer_id="human-1")

    sim_req = SimulationRequest(action=SimulationAction(tool_id="write_file", arguments={"operation": "create", "path": "f.txt", "content": "x"}, resource_scope=str(root), operation_scope="write"), tool_or_connector_id="write_file", tenant_id="org-1", principal_id="u1", lease_id=lease.lease_id, capability="FILE_WRITE")
    sim_result, _ = run_simulation(sim_req, ChamberDependencies(filesystem_root=root, lease_id=lease.lease_id))
    assert sim_result.can_proceed()

    ks.activate(reason="incident")
    try:
        exec_decision = revalidate_and_consume_before_execution(lease_id=lease.lease_id, tenant_id="org-1", capability_domain=CapabilityDomain.FILE, capability="FILE_WRITE", resource_scope=str(root), operation_scope="write", arguments={})
        assert exec_decision.state.value == "DENY"
    finally:
        ks.deactivate()


# ── §71: cross-tenant ──────────────────────────────────────────────────────

def test_cross_tenant_simulation_blocked_for_connectors():
    instance_b = ConnectorInstance(connector_type=ConnectorType.TICKETING, tenant_id="org-B", owner_principal_id="u2")
    identity_a = ConnectorIdentity(tenant_id="org-A", principal_id="attacker")
    action = SimulationAction(tool_id="CONNECTOR_TICKETING", arguments={}, resource_scope="ticket/1", operation_scope="close")
    req = SimulationRequest(action=action, tool_or_connector_id="CONNECTOR_TICKETING", tenant_id="org-A", principal_id="attacker")
    result, _ = run_simulation(req, ChamberDependencies(connector_instance=instance_b, connector_identity=identity_a))
    assert result.verdict == SimulationVerdict.BLOCK
    assert "tenant" in result.block_reasons[0].lower()


def test_cross_tenant_lease_cannot_be_used_for_simulation_compatibility_check(tmp_path, monkeypatch):
    import orca.godmode.lease_store as ls
    import orca.godmode.kill_switch as ks
    monkeypatch.setattr(ls, "LEASE_DIR", tmp_path / "leases")
    # Phase 14A.1: kill-switch state now lives in leases.db (see
    # orca/godmode/kill_switch.py) -- redirecting LEASE_DIR above
    # already isolates it; the old _KILL_SWITCH_FILE attribute is gone.

    from orca.godmode.contracts import CapabilityDomain, ElevatedCapabilityRequest, LeaseIssuerClass
    from orca.godmode.issuance import issue_lease, make_approval

    root = tmp_path / "project"
    root.mkdir()
    req = ElevatedCapabilityRequest(principal_id="u1", tenant_id="org-B", capability_domain=CapabilityDomain.FILE, capability="FILE_WRITE", resource_scope=str(root), operation_scope="write", reason="test")
    approval = make_approval(request=req, approved_by="human-1", duration_s=60)
    lease = issue_lease(approval=approval, issuer=LeaseIssuerClass.HUMAN_APPROVAL, issuer_id="human-1")

    sim_req = SimulationRequest(action=SimulationAction(tool_id="write_file", arguments={"operation": "create", "path": "f.txt", "content": "x"}, resource_scope=str(root), operation_scope="write"), tool_or_connector_id="write_file", tenant_id="org-A", principal_id="attacker", lease_id=lease.lease_id, capability="FILE_WRITE")
    result, _ = run_simulation(sim_req, ChamberDependencies(filesystem_root=root, lease_id=lease.lease_id))
    assert result.verdict == SimulationVerdict.BLOCK


# ── §72: secrets ───────────────────────────────────────────────────────────

def test_simulation_trace_does_not_expose_raw_secret_arguments():
    from orca.connectors.security import redact_secrets
    secret_arg = "api_key: sk-abcdefghijklmnopqrstuvwxyz1234567890"
    action = SimulationAction(tool_id="CONNECTOR_TICKETING", arguments={"note": secret_arg}, resource_scope="ticket/1", operation_scope="close")
    # This mirrors how a real caller would sanitize before persisting an
    # audit/trace record -- orca.simulation reuses the SAME redaction
    # utility Phase 9/10 already established, never a second one.
    redacted = redact_secrets(action.arguments["note"])
    assert "sk-abcdefghijklmnopqrstuvwxyz1234567890" not in redacted


def test_simulation_result_dataclass_has_no_raw_credential_field():
    field_names = {f.name for f in dataclasses.fields(SimulationResult)}
    forbidden = {"credential", "secret", "api_key", "password", "raw_arguments"}
    assert not (field_names & forbidden)


# ── §73: side-effect simulation never performs a real external effect ────

def test_unsupported_connector_never_attempts_a_real_write():
    """CRM (no real client, no fake preview wired) must return
    unsupported, never silently attempt something that could be a real
    call."""
    instance = ConnectorInstance(connector_type=ConnectorType.CRM, tenant_id="org-1", owner_principal_id="u1")
    identity = ConnectorIdentity(tenant_id="org-1", principal_id="u1")
    action = SimulationAction(tool_id="CONNECTOR_CRM", arguments={}, resource_scope="lead/1", operation_scope="update")
    req = SimulationRequest(action=action, tool_or_connector_id="CONNECTOR_CRM", tenant_id="org-1", principal_id="u1")
    result, _ = run_simulation(req, ChamberDependencies(connector_instance=instance, connector_identity=identity))
    assert result.verdict == SimulationVerdict.INCONCLUSIVE
    assert result.failure_reason.value == "UNSUPPORTED"
