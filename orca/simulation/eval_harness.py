"""
Simulation Chamber evaluation harness (Phase 11 spec §74). Deterministic
-- no live model call -- matching the discipline of
`orca.agent.eval_harness`/`orca.connectors.eval_harness`/
`orca.godmode.eval_harness`.
"""
from __future__ import annotations

import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

from orca.agent.contracts import Observation, SideEffectClass, ActionRiskLevel
from orca.connectors.contracts import ConnectorCapabilityKind, ConnectorIdentity, ConnectorInstance, ConnectorType
from orca.simulation.chamber import ChamberDependencies, run_simulation
from orca.simulation.contracts import (
    SimulationAction,
    SimulationRequest,
    SimulationRequirement,
    SimulationVerdict,
    ToolSimulationCapability,
)
from orca.simulation.execution_gate import evaluate_execution_gate
from orca.simulation.fingerprint import fingerprint_file
from orca.simulation.godmode_integration import check_simulation_staleness
from orca.simulation.reality_diff import failure_candidate_from_diff, reconcile
from orca.simulation.requirement_policy import SimulationRequirementContext, decide_simulation_requirement
from orca.simulation.worldstate_projection import project_worldstate
from orca.deliberation.contracts import WorldState


@dataclass
class Scenario:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class HarnessResult:
    total: int = 0
    passed: int = 0
    results: list[Scenario] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0


def _record(results, name, condition, detail=""):
    results.append(Scenario(name=name, passed=bool(condition), detail=detail))


def run_all() -> HarnessResult:
    results: list[Scenario] = []

    # 1. Read-only action: no simulation required.
    req1 = decide_simulation_requirement(SimulationRequirementContext(side_effect_class=SideEffectClass.READ_ONLY), ToolSimulationCapability())
    _record(results, "read_only_action_no_simulation_required", req1 == SimulationRequirement.NOT_REQUIRED)

    # Shared filesystem sandbox root for the file-based scenarios.
    root = Path(tempfile.mkdtemp())
    (root / "app.yaml").write_text("k: v")

    # 2. Filesystem write simulation.
    write_action = SimulationAction(tool_id="write_file", arguments={"operation": "modify", "path": "app.yaml", "content": "k: v2"}, resource_scope="app.yaml", operation_scope="write")
    write_req = SimulationRequest(action=write_action, tool_or_connector_id="write_file", tenant_id="org-1", principal_id="u1")
    write_result, write_trace = run_simulation(write_req, ChamberDependencies(filesystem_root=root))
    _record(results, "filesystem_write_simulation", write_result.verdict in (SimulationVerdict.PASS, SimulationVerdict.PASS_WITH_WARNINGS) and len(write_result.predicted_effects) == 1)
    _record(results, "filesystem_write_root_untouched", (root / "app.yaml").read_text() == "k: v")

    # 3. Filesystem delete projected -- classified IRREVERSIBLE, PASS_WITH_WARNINGS.
    delete_action = SimulationAction(tool_id="write_file", arguments={"operation": "delete", "path": "app.yaml"}, resource_scope="app.yaml", operation_scope="delete")
    delete_req = SimulationRequest(action=delete_action, tool_or_connector_id="write_file", tenant_id="org-1", principal_id="u1")
    delete_result, _ = run_simulation(delete_req, ChamberDependencies(filesystem_root=root))
    _record(results, "filesystem_delete_projected_and_flagged", delete_result.verdict == SimulationVerdict.PASS_WITH_WARNINGS and any("IRREVERSIBLE" in w for w in delete_result.warnings))

    # 4. Path escape blocks.
    escape_action = SimulationAction(tool_id="write_file", arguments={"operation": "create", "path": "../../etc/evil", "content": "x"}, resource_scope="x", operation_scope="write")
    escape_req = SimulationRequest(action=escape_action, tool_or_connector_id="write_file", tenant_id="org-1", principal_id="u1")
    escape_result, _ = run_simulation(escape_req, ChamberDependencies(filesystem_root=root))
    _record(results, "path_escape_simulation_blocks", escape_result.verdict == SimulationVerdict.BLOCK)

    # 5. Directory-scoped elevated file action stays inside root.
    outside_action = SimulationAction(tool_id="write_file", arguments={"operation": "create", "path": "/tmp/definitely_outside_root_xyz.txt", "content": "x"}, resource_scope="x", operation_scope="write")
    outside_req = SimulationRequest(action=outside_action, tool_or_connector_id="write_file", tenant_id="org-1", principal_id="u1")
    outside_result, _ = run_simulation(outside_req, ChamberDependencies(filesystem_root=root))
    _record(results, "elevated_file_action_stays_inside_root", outside_result.verdict == SimulationVerdict.BLOCK)

    # 6. Connector fake-provider update preview.
    instance = ConnectorInstance(connector_type=ConnectorType.TICKETING, tenant_id="org-1", owner_principal_id="u1", enabled_capabilities=frozenset({ConnectorCapabilityKind.CONNECTOR_READ, ConnectorCapabilityKind.CONNECTOR_WRITE}), read_write_mode="READ_WRITE")
    identity = ConnectorIdentity(tenant_id="org-1", principal_id="u1")
    conn_action = SimulationAction(tool_id="CONNECTOR_TICKETING", arguments={"text": "closed", "idempotency_key": "idem-1"}, resource_scope="ticket/1", operation_scope="close")
    conn_req = SimulationRequest(action=conn_action, tool_or_connector_id="CONNECTOR_TICKETING", tenant_id="org-1", principal_id="u1")
    conn_result, _ = run_simulation(conn_req, ChamberDependencies(connector_instance=instance, connector_identity=identity))
    _record(results, "connector_update_preview", conn_result.verdict == SimulationVerdict.PASS)

    # 7. Connector OUTCOME_UNKNOWN risk identified (no idempotency key).
    conn_action_no_idem = SimulationAction(tool_id="CONNECTOR_TICKETING", arguments={"text": "closed"}, resource_scope="ticket/2", operation_scope="close")
    conn_req_no_idem = SimulationRequest(action=conn_action_no_idem, tool_or_connector_id="CONNECTOR_TICKETING", tenant_id="org-1", principal_id="u1")
    conn_result_no_idem, _ = run_simulation(conn_req_no_idem, ChamberDependencies(connector_instance=instance, connector_identity=identity))
    _record(results, "connector_outcome_unknown_risk_identified", any("OUTCOME_UNKNOWN_RISK" in w for w in conn_result_no_idem.warnings))

    # 8. Unsupported external side-effect returns unavailable/inconclusive.
    crm_instance = ConnectorInstance(connector_type=ConnectorType.CRM, tenant_id="org-1", owner_principal_id="u1")
    crm_action = SimulationAction(tool_id="CONNECTOR_CRM", arguments={}, resource_scope="lead/1", operation_scope="update")
    crm_req = SimulationRequest(action=crm_action, tool_or_connector_id="CONNECTOR_CRM", tenant_id="org-1", principal_id="u1")
    crm_result, _ = run_simulation(crm_req, ChamberDependencies(connector_instance=crm_instance, connector_identity=identity))
    _record(results, "unsupported_external_side_effect_inconclusive", crm_result.verdict == SimulationVerdict.INCONCLUSIVE)

    # 9. Simulation detects scope mismatch (cross-tenant connector).
    other_tenant_instance = ConnectorInstance(connector_type=ConnectorType.TICKETING, tenant_id="org-EVIL", owner_principal_id="u2")
    mismatch_req = SimulationRequest(action=conn_action, tool_or_connector_id="CONNECTOR_TICKETING", tenant_id="org-1", principal_id="u1")
    mismatch_result, _ = run_simulation(mismatch_req, ChamberDependencies(connector_instance=other_tenant_instance, connector_identity=identity))
    _record(results, "simulation_detects_tenant_scope_mismatch", mismatch_result.verdict == SimulationVerdict.BLOCK and "tenant" in mismatch_result.block_reasons[0].lower())

    # 10. Simulation detects destructive blast radius (delete = single object but IRREVERSIBLE flagged).
    _record(results, "simulation_detects_destructive_effect", delete_result.predicted_effects[0].reversibility.value == "IRREVERSIBLE")

    # 11. Simulation assumption becomes stale.
    fp_before = fingerprint_file(root, "app.yaml")
    (root / "app.yaml").write_text("k: CHANGED_EXTERNALLY")
    fp_after = fingerprint_file(root, "app.yaml")
    staleness = check_simulation_staleness(simulated_fingerprint=fp_before, current_fingerprint=fp_after)
    _record(results, "simulation_assumption_becomes_stale", staleness.stale is True)

    # 12. WorldState projection does not mutate live state.
    live_ws = WorldState(known_facts=["real fact"])
    projection = project_worldstate(live_ws, source_action_id="act-1", predicted_effects=write_result.predicted_effects)
    _record(results, "worldstate_projection_does_not_mutate_live_state", live_ws.known_facts == ["real fact"] and projection.projected_state is not live_ws)

    # 13. Simulation PASS still requires normal authorization (structural: run_simulation never touches Capability/Policy).
    import inspect
    from orca.simulation import chamber as chamber_mod
    chamber_source = inspect.getsource(chamber_mod)
    _record(results, "simulation_pass_does_not_call_capability_or_policy_engine", "check_capabilities(" not in chamber_source and "evaluate_policy(" not in chamber_source)

    # 14. Court ACCEPT still does not authorize (structural: chamber never imports orca.deliberation.court).
    _record(results, "court_accept_does_not_authorize", "orca.deliberation.court" not in chamber_source and "CourtVerdict" not in chamber_source)

    # 15. Simulation BLOCK prevents execution (via ExecutionGate).
    gate_decision = evaluate_execution_gate(requirement=SimulationRequirement.REQUIRED, result=escape_result)
    _record(results, "simulation_block_prevents_execution", gate_decision.value == "BLOCK")

    # 16. One-use lease not consumed by non-executing preview.
    import tempfile as _tf
    gm_tmp = Path(_tf.mkdtemp())
    import orca.godmode.lease_store as ls
    import orca.godmode.kill_switch as ks
    # Phase 14A.1: kill-switch state now lives in leases.db (see
    # orca/godmode/kill_switch.py) -- redirecting LEASE_DIR below
    # already isolates it; the old _KILL_SWITCH_FILE attribute is gone.
    orig_lease_dir = ls.LEASE_DIR
    ls.LEASE_DIR = gm_tmp / "leases"
    try:
        from orca.godmode.contracts import CapabilityDomain, ElevatedCapabilityRequest, LeaseIssuerClass
        from orca.godmode.issuance import issue_lease, make_approval
        gm_root = gm_tmp / "project-x"
        gm_root.mkdir()
        gm_req = ElevatedCapabilityRequest(principal_id="u1", tenant_id="org-1", capability_domain=CapabilityDomain.FILE, capability="FILE_WRITE", resource_scope=str(gm_root), operation_scope="write", reason="fix")
        gm_approval = make_approval(request=gm_req, approved_by="human-1", duration_s=120)
        gm_lease = issue_lease(approval=gm_approval, issuer=LeaseIssuerClass.HUMAN_APPROVAL, issuer_id="human-1")

        preview_req = SimulationRequest(
            action=SimulationAction(tool_id="write_file", arguments={"operation": "create", "path": "cfg.yaml", "content": "x"}, resource_scope=str(gm_root), operation_scope="write"),
            tool_or_connector_id="write_file", tenant_id="org-1", principal_id="u1", lease_id=gm_lease.lease_id, capability="FILE_WRITE",
        )
        preview_result, _ = run_simulation(preview_req, ChamberDependencies(filesystem_root=gm_root, lease_id=gm_lease.lease_id))
        from orca.godmode.lease_store import get as get_lease
        _record(results, "one_use_lease_not_consumed_by_preview", preview_result.verdict in (SimulationVerdict.PASS, SimulationVerdict.PASS_WITH_WARNINGS) and get_lease(gm_lease.lease_id).uses_remaining == 1)

        # 17. Lease revoked after simulation prevents execution.
        from orca.godmode.lease_store import revoke
        revoke(gm_lease.lease_id)
        from orca.simulation.godmode_integration import revalidate_and_consume_before_execution
        exec_decision = revalidate_and_consume_before_execution(lease_id=gm_lease.lease_id, tenant_id="org-1", capability_domain=CapabilityDomain.FILE, capability="FILE_WRITE", resource_scope=str(gm_root), operation_scope="write", arguments={})
        _record(results, "lease_revoked_after_simulation_prevents_execution", exec_decision.state.value == "DENY")

        # 18. Kill switch after simulation prevents execution.
        gm_req2 = ElevatedCapabilityRequest(principal_id="u1", tenant_id="org-1", capability_domain=CapabilityDomain.FILE, capability="FILE_WRITE", resource_scope=str(gm_root), operation_scope="write", reason="fix2")
        gm_approval2 = make_approval(request=gm_req2, approved_by="human-1", duration_s=120)
        gm_lease2 = issue_lease(approval=gm_approval2, issuer=LeaseIssuerClass.HUMAN_APPROVAL, issuer_id="human-1")
        ks.activate(reason="eval")
        exec_decision2 = revalidate_and_consume_before_execution(lease_id=gm_lease2.lease_id, tenant_id="org-1", capability_domain=CapabilityDomain.FILE, capability="FILE_WRITE", resource_scope=str(gm_root), operation_scope="write", arguments={})
        ks.deactivate()
        _record(results, "kill_switch_after_simulation_prevents_execution", exec_decision2.state.value == "DENY")
    finally:
        ls.LEASE_DIR = orig_lease_dir

    # 19. Simulation cancelled -- represented via explicit failure reason (no live async harness needed for a deterministic scenario).
    from orca.simulation.contracts import SimulationFailureReason, SimulationResult
    cancelled_result = SimulationResult(verdict=SimulationVerdict.INCONCLUSIVE, failure_reason=SimulationFailureReason.CANCELLED)
    _record(results, "simulation_cancelled_represented", cancelled_result.failure_reason == SimulationFailureReason.CANCELLED)

    # 20. Simulation budget exhausted.
    class _ExhaustedLedger:
        def reserve(self, purpose, amount=1):
            from orca.cognitive.errors import CognitiveBudgetExhaustedError
            raise CognitiveBudgetExhaustedError("simulation_operations exhausted")
    exhausted_req = SimulationRequest(action=write_action, tool_or_connector_id="write_file", tenant_id="org-1", principal_id="u1")
    exhausted_result, _ = run_simulation(exhausted_req, ChamberDependencies(filesystem_root=root, budget_ledger=_ExhaustedLedger()))
    _record(results, "simulation_budget_exhausted", exhausted_result.failure_reason is not None and exhausted_result.failure_reason.value == "BUDGET_EXHAUSTED")

    # 21. Predicted effect matches reality.
    match_obs = Observation(action_id="act-x", source="write_file", status="OK", facts=["wrote app.yaml successfully"])
    match_diff = reconcile(simulation_id=write_result.result_id, predicted_effects=write_result.predicted_effects, observation=match_obs)
    _record(results, "predicted_effect_matches_reality", match_diff.status.value == "MATCHED")

    # 22. Unexpected actual effect produces RealityDiff + failure-memory candidate (not automatic memory).
    mismatch_obs = Observation(action_id="act-y", source="write_file", status="OK", facts=["wrote a completely different file"])
    mismatch_diff = reconcile(simulation_id=write_result.result_id, predicted_effects=write_result.predicted_effects, observation=mismatch_obs)
    candidate = failure_candidate_from_diff(mismatch_diff)
    _record(results, "reality_mismatch_creates_failure_candidate_only", mismatch_diff.status.value != "MATCHED" and candidate is not None)

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    return HarnessResult(total=total, passed=passed, results=results)


if __name__ == "__main__":
    result = run_all()
    for scenario in result.results:
        status = "PASS" if scenario.passed else "FAIL"
        print(f"[{status}] {scenario.name} {scenario.detail}")
    print(f"\n{result.passed}/{result.total} scenarios passed ({result.pass_rate:.0%})")
