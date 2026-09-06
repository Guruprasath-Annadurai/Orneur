"""
Phase 11.1 closure evaluation harness (spec §48). Deterministic -- no
live model call for the pure-mechanism scenarios; the original Phase 11
23-scenario harness (`orca/simulation/eval_harness.py`) is preserved
unchanged and remains independently green.
"""
from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from orca.agent.contracts import AgentAction, AgentPlan, AgentTask, Observation
from orca.simulation.branching import BranchLabel, MAX_SIMULATION_BRANCHES, run_bounded_branches
from orca.simulation.contracts import Assumption, EffectType, PredictedEffect, SimulationVerdict
from orca.simulation.plan_chamber import MAX_SIMULATION_ACTIONS, simulate_plan, simulate_plan_async
from orca.simulation.reality_diff import reconcile_plan
from orca.simulation.truth_impact import apply_truth_impact_to_verdict
from orca.simulation.truth_verification import AssumptionVerificationContext, verify_assumption


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


def _chain_plan(root: Path, n: int) -> AgentPlan:
    tasks, actions, prev = [], [], None
    for i in range(n):
        t = AgentTask(description=f"step {i}", dependencies=[prev.task_id] if prev else [])
        a = AgentAction(task_id=t.task_id, tool_id="write_file", arguments={"operation": "create" if i == 0 else "modify", "path": "chain.txt", "content": f"v{i}"})
        tasks.append(t)
        actions.append(a)
        prev = t
    return AgentPlan(tasks=tasks, actions=actions)


def run_all() -> HarnessResult:
    results: list[Scenario] = []

    root = Path(tempfile.mkdtemp())

    # 1. Two-action projection chain.
    plan2 = _chain_plan(root, 2)
    r2 = simulate_plan(plan2, filesystem_root=root)
    _record(results, "two_action_projection_chain", r2.per_action[1].predicted_effects[0].before_reference == r2.per_action[0].predicted_effects[0].predicted_after_reference)

    # 2. Dependency-blocked simulation.
    root_dep = Path(tempfile.mkdtemp())
    t_a = AgentTask(description="delete missing")
    t_b = AgentTask(description="b", dependencies=[t_a.task_id])
    a_a = AgentAction(task_id=t_a.task_id, tool_id="write_file", arguments={"operation": "delete", "path": "missing.txt"})
    a_b = AgentAction(task_id=t_b.task_id, tool_id="write_file", arguments={"operation": "create", "path": "b.txt", "content": "x"})
    r_dep = simulate_plan(AgentPlan(tasks=[t_a, t_b], actions=[a_a, a_b]), filesystem_root=root_dep)
    _record(results, "dependency_blocked_simulation", r_dep.per_action[1].status == "BLOCKED_BY_DEPENDENCY")

    # 3. Multi-action aggregate blast radius.
    root_blast = Path(tempfile.mkdtemp())
    t1 = AgentTask(description="1")
    t2 = AgentTask(description="2", dependencies=[t1.task_id])
    a1 = AgentAction(task_id=t1.task_id, tool_id="write_file", arguments={"operation": "create", "path": "one.txt", "content": "x"})
    a2 = AgentAction(task_id=t2.task_id, tool_id="write_file", arguments={"operation": "create", "path": "two.txt", "content": "y"})
    r_blast = simulate_plan(AgentPlan(tasks=[t1, t2], actions=[a1, a2]), filesystem_root=root_blast)
    _record(results, "multi_action_aggregate_blast_radius", r_blast.aggregate_blast_radius.value == "MULTIPLE_OBJECTS")

    # 4. Multi-action aggregate reversibility.
    root_rev = Path(tempfile.mkdtemp())
    (root_rev / "keep.txt").write_text("x")
    t3 = AgentTask(description="create")
    t4 = AgentTask(description="delete", dependencies=[t3.task_id])
    a3 = AgentAction(task_id=t3.task_id, tool_id="write_file", arguments={"operation": "create", "path": "new.txt", "content": "x"})
    a4 = AgentAction(task_id=t4.task_id, tool_id="write_file", arguments={"operation": "delete", "path": "keep.txt"})
    r_rev = simulate_plan(AgentPlan(tasks=[t3, t4], actions=[a3, a4]), filesystem_root=root_rev)
    _record(results, "multi_action_aggregate_reversibility", r_rev.aggregate_reversibility.value == "IRREVERSIBLE")

    # 5. Branch success/failure outcomes.
    root_branch = Path(tempfile.mkdtemp())
    (root_branch / "x.txt").write_text("v0")
    t5 = AgentTask(description="create")
    t6 = AgentTask(description="delete", dependencies=[t5.task_id])
    a5 = AgentAction(task_id=t5.task_id, tool_id="write_file", arguments={"operation": "create", "path": "y.txt", "content": "v1"})
    a6 = AgentAction(task_id=t6.task_id, tool_id="write_file", arguments={"operation": "delete", "path": "x.txt"})
    branched = run_bounded_branches(AgentPlan(tasks=[t5, t6], actions=[a5, a6]), filesystem_root=root_branch)
    _record(results, "branch_success_and_failure_outcomes", {b.label for b in branched.branches} == {BranchLabel.EXPECTED_SUCCESS, BranchLabel.EXPECTED_FAILURE})

    # 6. Branch maximum enforced.
    root_many = Path(tempfile.mkdtemp())
    tasks_many, actions_many, prev = [], [], None
    for i in range(5):
        (root_many / f"f{i}.txt").write_text("v")
        t = AgentTask(description=f"del {i}", dependencies=[prev.task_id] if prev else [])
        a = AgentAction(task_id=t.task_id, tool_id="write_file", arguments={"operation": "delete", "path": f"f{i}.txt"})
        tasks_many.append(t); actions_many.append(a); prev = t
    branched_many = run_bounded_branches(AgentPlan(tasks=tasks_many, actions=actions_many), filesystem_root=root_many)
    _record(results, "branch_maximum_enforced", branched_many.branch_count <= MAX_SIMULATION_BRANCHES)

    # 7. Branch state isolation.
    _record(results, "branch_state_isolation", (root_branch / "x.txt").exists())  # real root untouched by either branch's sandbox

    # 8. Branch budget shared.
    class _CountingLedger:
        def __init__(self):
            self.n = 0
        def reserve(self, purpose, amount=1):
            self.n += 1
    ledger = _CountingLedger()
    branched2 = run_bounded_branches(AgentPlan(tasks=[t5, t6], actions=[a5, a6]), filesystem_root=root_branch, budget_ledger=ledger)
    _record(results, "branch_budget_shared", ledger.n == branched2.branch_count)

    # 9. Fresh external assumption triggers Truth.
    from orca.simulation.truth_verification import requires_truth_verification
    _record(results, "fresh_external_assumption_triggers_truth", requires_truth_verification(AssumptionVerificationContext(externally_factual=True)) and not requires_truth_verification(AssumptionVerificationContext()))

    # 10. Truth SUFFICIENT keeps PASS.
    from orca.docs.store import DocStore
    from orca.docs.chunker import chunk_text
    store = DocStore(session_id="sim-eval-v2-truth")
    store.add_chunks(chunk_text("The release window is Friday at noon.", doc_id="d1", filename="f.txt"), doc_id="d1", filename="f.txt")
    a_claim = Assumption(description="the release window is Friday at noon", source="plan")
    verified = asyncio.run(verify_assumption(a_claim, simulation_id="sim-1", ctx=AssumptionVerificationContext(externally_factual=True), doc_store=store))
    verdict_ok, _ = apply_truth_impact_to_verdict(SimulationVerdict.PASS, [verified], is_high_risk=True)
    _record(results, "truth_sufficient_keeps_pass", verdict_ok == SimulationVerdict.PASS)

    # 11. Truth CONFLICTED changes verdict.
    contested = Assumption(description="x", source="truth_fabric_verification", verification_state="CONTESTED")
    verdict_revise, _ = apply_truth_impact_to_verdict(SimulationVerdict.PASS, [contested], is_high_risk=True)
    _record(results, "truth_conflicted_changes_verdict", verdict_revise == SimulationVerdict.REVISE)

    # 12. Truth INSUFFICIENT prevents high-risk PASS.
    unverified = Assumption(description="x", source="truth_fabric_verification", verification_state="UNVERIFIED")
    verdict_inconclusive, _ = apply_truth_impact_to_verdict(SimulationVerdict.PASS, [unverified], is_high_risk=True)
    _record(results, "truth_insufficient_prevents_high_risk_pass", verdict_inconclusive == SimulationVerdict.INCONCLUSIVE)

    # 13-15. Cancellation scenarios.
    root_cancel = Path(tempfile.mkdtemp())
    plan_cancel = _chain_plan(root_cancel, 3)

    async def _cancel_between():
        t = asyncio.create_task(simulate_plan_async(plan_cancel, filesystem_root=root_cancel))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        t.cancel()
        return await t
    cancel_result = asyncio.run(_cancel_between())
    _record(results, "cancel_between_actions", cancel_result.aggregate_verdict == SimulationVerdict.INCONCLUSIVE and len(cancel_result.action_order) < 3)
    _record(results, "partial_multi_action_result_on_cancel", len(cancel_result.action_order) >= 1)

    async def _no_orphan():
        t = asyncio.create_task(simulate_plan_async(plan_cancel, filesystem_root=root_cancel))
        await asyncio.sleep(0)
        t.cancel()
        await t
        return [tk for tk in asyncio.all_tasks() if not tk.done() and tk is not asyncio.current_task()]
    pending = asyncio.run(_no_orphan())
    _record(results, "no_orphan_simulation_task", pending == [])

    # 16. Projected action A influences simulated B (already scenario 1, re-recorded distinctly per spec wording).
    _record(results, "projected_action_a_influences_simulated_b", r2.per_action[1].predicted_effects[0].before_reference is not None)

    # 17. Real WorldState unchanged.
    from orca.deliberation.contracts import WorldState
    live_ws = WorldState(known_facts=["real"])
    r_ws = simulate_plan(plan2, filesystem_root=root, live_world_state=live_ws)
    _record(results, "real_worldstate_unchanged", live_ws.known_facts == ["real"] and r_ws.projected_world_state is not live_ws)

    # 18. Elevated multi-action preview consumes no lease use.
    gm_tmp = Path(tempfile.mkdtemp())
    import orca.godmode.lease_store as ls
    import orca.godmode.kill_switch as ks
    # Phase 14A.1: kill-switch state now lives in leases.db (see
    # orca/godmode/kill_switch.py) -- redirecting LEASE_DIR below
    # already isolates it; the old _KILL_SWITCH_FILE attribute is gone.
    orig_dir = ls.LEASE_DIR
    ls.LEASE_DIR = gm_tmp / "leases"
    try:
        from orca.godmode.contracts import CapabilityDomain, ElevatedCapabilityRequest, LeaseIssuerClass
        from orca.godmode.issuance import issue_lease, make_approval
        from orca.godmode.lease_store import get as get_lease
        gm_root = gm_tmp / "project"
        gm_root.mkdir()
        gm_req = ElevatedCapabilityRequest(principal_id="u1", tenant_id="org-1", capability_domain=CapabilityDomain.FILE, capability="FILE_WRITE", resource_scope=str(gm_root), operation_scope="write", reason="test")
        gm_approval = make_approval(request=gm_req, approved_by="human-1", duration_s=60)
        gm_lease = issue_lease(approval=gm_approval, issuer=LeaseIssuerClass.HUMAN_APPROVAL, issuer_id="human-1")
        gm_plan = _chain_plan(gm_root, 2)
        simulate_plan(gm_plan, filesystem_root=gm_root)  # plan_chamber never touches godmode at all
        _record(results, "elevated_multiaction_preview_consumes_no_lease", get_lease(gm_lease.lease_id).uses_remaining == 1)

        # 19. Real action revalidates lease independently.
        from orca.godmode.resolution import resolve_and_consume_lease
        decision = resolve_and_consume_lease(gm_lease.lease_id, tenant_id="org-1", capability_domain=CapabilityDomain.FILE, capability="FILE_WRITE", resource_scope=str(gm_root), operation_scope="write", arguments={})
        _record(results, "real_action_revalidates_lease_independently", decision.state.value == "ALLOW" and get_lease(gm_lease.lease_id).uses_remaining == 0)
    finally:
        ls.LEASE_DIR = orig_dir

    # 20. Plan RealityDiff match.
    obs_match = Observation(action_id=r2.action_order[0], source="write_file", status="OK", facts=["wrote chain.txt"])
    obs_match2 = Observation(action_id=r2.action_order[1], source="write_file", status="OK", facts=["wrote chain.txt"])
    diff_match = reconcile_plan(plan_simulation_id=r2.plan_simulation_id, per_action_predicted=[(r2.action_order[0], r2.per_action[0].predicted_effects), (r2.action_order[1], r2.per_action[1].predicted_effects)], observations={r2.action_order[0]: obs_match, r2.action_order[1]: obs_match2})
    _record(results, "plan_reality_diff_match", diff_match.aggregate_status.value == "MATCHED")

    # 21. Plan RealityDiff mismatch stops/replans remaining actions.
    obs_mismatch = Observation(action_id=r2.action_order[1], source="write_file", status="OK", facts=["wrote something unrelated"])
    diff_mismatch = reconcile_plan(plan_simulation_id=r2.plan_simulation_id, per_action_predicted=[(r2.action_order[1], r2.per_action[1].predicted_effects)], observations={r2.action_order[1]: obs_mismatch})
    _record(results, "plan_reality_mismatch_halts_remaining", diff_mismatch.remaining_actions_halted is True)

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    return HarnessResult(total=total, passed=passed, results=results)


if __name__ == "__main__":
    result = run_all()
    for scenario in result.results:
        status = "PASS" if scenario.passed else "FAIL"
        print(f"[{status}] {scenario.name} {scenario.detail}")
    print(f"\n{result.passed}/{result.total} scenarios passed ({result.pass_rate:.0%})")
