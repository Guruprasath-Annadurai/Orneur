"""
Phase 11.1 closure: multi-action plan simulation, bounded branching,
real Truth Fabric integration, async cancellation. Covers spec §42-46
security scenarios and the §48 closure eval cases not already covered
by orca/simulation/eval_harness_v2.py.
"""
from __future__ import annotations

import asyncio
import inspect
import tempfile
from pathlib import Path

import pytest

from orca.agent.contracts import AgentAction, AgentPlan, AgentTask, Observation
from orca.simulation.branching import BranchLabel, MAX_SIMULATION_BRANCHES, run_bounded_branches
from orca.simulation.contracts import Assumption, EffectConfidence, SimulationVerdict
from orca.simulation.plan_chamber import MAX_SIMULATION_ACTIONS, PlanDependencyError, simulate_plan, simulate_plan_async
from orca.simulation.reality_diff import reconcile_plan
from orca.simulation.truth_impact import apply_truth_impact_to_verdict
from orca.simulation.truth_verification import AssumptionVerificationContext, verify_assumption


def _chain_plan(root: Path, n: int):
    tasks, actions, prev = [], [], None
    for i in range(n):
        t = AgentTask(description=f"step {i}", dependencies=[prev.task_id] if prev else [])
        a = AgentAction(task_id=t.task_id, tool_id="write_file", arguments={"operation": "create" if i == 0 else "modify", "path": "chain.txt", "content": f"v{i}"})
        tasks.append(t)
        actions.append(a)
        prev = t
    return AgentPlan(tasks=tasks, actions=actions)


# ── dependency ordering / projected state chain ──────────────────────────

def test_two_action_filesystem_projection_chain():
    root = Path(tempfile.mkdtemp())
    plan = _chain_plan(root, 2)
    result = simulate_plan(plan, filesystem_root=root)
    assert result.aggregate_verdict == SimulationVerdict.PASS
    a_effect, b_effect = result.per_action[0].predicted_effects[0], result.per_action[1].predicted_effects[0]
    assert b_effect.before_reference == a_effect.predicted_after_reference
    assert not (root / "chain.txt").exists()


def test_dependency_blocked_simulation():
    root = Path(tempfile.mkdtemp())
    task_a = AgentTask(description="delete nonexistent")
    task_b = AgentTask(description="depends on a", dependencies=[task_a.task_id])
    action_a = AgentAction(task_id=task_a.task_id, tool_id="write_file", arguments={"operation": "delete", "path": "missing.txt"})
    action_b = AgentAction(task_id=task_b.task_id, tool_id="write_file", arguments={"operation": "create", "path": "b.txt", "content": "x"})
    plan = AgentPlan(tasks=[task_a, task_b], actions=[action_a, action_b])
    result = simulate_plan(plan, filesystem_root=root)
    assert result.per_action[0].verdict == SimulationVerdict.BLOCK
    assert result.per_action[1].status == "BLOCKED_BY_DEPENDENCY"
    assert not (root / "b.txt").exists()


def test_invalid_dependency_reference_fails_structurally():
    task = AgentTask(description="x", dependencies=["does-not-exist"])
    plan = AgentPlan(tasks=[task], actions=[])
    result = simulate_plan(plan)
    assert result.aggregate_verdict == SimulationVerdict.BLOCK


def test_cyclic_dependency_fails_structurally():
    t1 = AgentTask(description="1")
    t2 = AgentTask(description="2", dependencies=[t1.task_id])
    t1.dependencies = [t2.task_id]  # cycle
    plan = AgentPlan(tasks=[t1, t2], actions=[])
    result = simulate_plan(plan)
    assert result.aggregate_verdict == SimulationVerdict.BLOCK


def test_oversized_plan_rejected_never_silently_truncated():
    root = Path(tempfile.mkdtemp())
    plan = _chain_plan(root, MAX_SIMULATION_ACTIONS + 3)
    result = simulate_plan(plan, filesystem_root=root)
    assert result.aggregate_verdict == SimulationVerdict.BLOCK
    assert result.partial is True
    assert result.action_order == []  # never partially ran and claimed PASS


# ── aggregate blast radius / reversibility ────────────────────────────────

def test_multi_action_aggregate_blast_radius_escalates():
    root = Path(tempfile.mkdtemp())
    task_a = AgentTask(description="create a")
    task_b = AgentTask(description="create b", dependencies=[task_a.task_id])
    action_a = AgentAction(task_id=task_a.task_id, tool_id="write_file", arguments={"operation": "create", "path": "a.txt", "content": "x"})
    action_b = AgentAction(task_id=task_b.task_id, tool_id="write_file", arguments={"operation": "create", "path": "b.txt", "content": "y"})
    plan = AgentPlan(tasks=[task_a, task_b], actions=[action_a, action_b])
    result = simulate_plan(plan, filesystem_root=root)
    assert result.aggregate_blast_radius.value == "MULTIPLE_OBJECTS"  # two distinct resources, never just the first action's SINGLE_OBJECT


def test_multi_action_aggregate_reversibility_is_worst_case():
    root = Path(tempfile.mkdtemp())
    (root / "keep.txt").write_text("x")
    task_a = AgentTask(description="create")
    task_b = AgentTask(description="delete", dependencies=[task_a.task_id])
    action_a = AgentAction(task_id=task_a.task_id, tool_id="write_file", arguments={"operation": "create", "path": "new.txt", "content": "x"})
    action_b = AgentAction(task_id=task_b.task_id, tool_id="write_file", arguments={"operation": "delete", "path": "keep.txt"})
    plan = AgentPlan(tasks=[task_a, task_b], actions=[action_a, action_b])
    result = simulate_plan(plan, filesystem_root=root)
    assert result.aggregate_reversibility.value == "IRREVERSIBLE"  # worst of {COMPENSATABLE, IRREVERSIBLE}


# ── branching ──────────────────────────────────────────────────────────────

def test_branch_success_and_failure_outcomes():
    root = Path(tempfile.mkdtemp())
    (root / "x.txt").write_text("v0")
    task_a = AgentTask(description="create")
    task_b = AgentTask(description="delete", dependencies=[task_a.task_id])
    action_a = AgentAction(task_id=task_a.task_id, tool_id="write_file", arguments={"operation": "create", "path": "y.txt", "content": "v1"})
    action_b = AgentAction(task_id=task_b.task_id, tool_id="write_file", arguments={"operation": "delete", "path": "x.txt"})
    plan = AgentPlan(tasks=[task_a, task_b], actions=[action_a, action_b])
    branched = run_bounded_branches(plan, filesystem_root=root)
    labels = {b.label for b in branched.branches}
    assert labels == {BranchLabel.EXPECTED_SUCCESS, BranchLabel.EXPECTED_FAILURE}


def test_branch_maximum_enforced_under_adversarial_plan():
    root = Path(tempfile.mkdtemp())
    tasks, actions, prev = [], [], None
    for i in range(6):
        (root / f"f{i}.txt").write_text("v")
        t = AgentTask(description=f"delete {i}", dependencies=[prev.task_id] if prev else [])
        a = AgentAction(task_id=t.task_id, tool_id="write_file", arguments={"operation": "delete", "path": f"f{i}.txt"})
        tasks.append(t)
        actions.append(a)
        prev = t
    plan = AgentPlan(tasks=tasks, actions=actions)
    branched = run_bounded_branches(plan, filesystem_root=root)
    assert branched.branch_count <= MAX_SIMULATION_BRANCHES


def test_branch_state_isolation():
    """Branch A's sandbox must never be visible to/mutated by Branch B."""
    root = Path(tempfile.mkdtemp())
    (root / "shared.txt").write_text("original")
    task_a = AgentTask(description="create")
    task_b = AgentTask(description="delete", dependencies=[task_a.task_id])
    action_a = AgentAction(task_id=task_a.task_id, tool_id="write_file", arguments={"operation": "create", "path": "new.txt", "content": "x"})
    action_b = AgentAction(task_id=task_b.task_id, tool_id="write_file", arguments={"operation": "delete", "path": "shared.txt"})
    plan = AgentPlan(tasks=[task_a, task_b], actions=[action_a, action_b])
    branched = run_bounded_branches(plan, filesystem_root=root)
    assert (root / "shared.txt").read_text() == "original"  # real root, hence every branch's sandbox, untouched


def test_branch_budget_shared_from_parent():
    class _CountingLedger:
        def __init__(self):
            self.reservations = 0
        def reserve(self, purpose, amount=1):
            self.reservations += 1
    root = Path(tempfile.mkdtemp())
    (root / "x.txt").write_text("v0")
    task_a = AgentTask(description="create")
    task_b = AgentTask(description="delete", dependencies=[task_a.task_id])
    action_a = AgentAction(task_id=task_a.task_id, tool_id="write_file", arguments={"operation": "create", "path": "y.txt", "content": "v1"})
    action_b = AgentAction(task_id=task_b.task_id, tool_id="write_file", arguments={"operation": "delete", "path": "x.txt"})
    plan = AgentPlan(tasks=[task_a, task_b], actions=[action_a, action_b])
    ledger = _CountingLedger()
    branched = run_bounded_branches(plan, filesystem_root=root, budget_ledger=ledger)
    assert ledger.reservations == branched.branch_count  # one reservation per branch, same ledger, no fresh allowance


def test_branch_budget_exhausted_yields_no_branches():
    class _ExhaustedLedger:
        def reserve(self, purpose, amount=1):
            from orca.cognitive.errors import CognitiveBudgetExhaustedError
            raise CognitiveBudgetExhaustedError("exhausted")
    root = Path(tempfile.mkdtemp())
    plan = _chain_plan(root, 2)
    branched = run_bounded_branches(plan, filesystem_root=root, budget_ledger=_ExhaustedLedger())
    assert branched.branch_count == 0


# ── real Truth Fabric integration ─────────────────────────────────────────

def test_fresh_external_assumption_triggers_truth():
    ctx = AssumptionVerificationContext(externally_factual=True)
    from orca.simulation.truth_verification import requires_truth_verification
    assert requires_truth_verification(ctx) is True
    assert requires_truth_verification(AssumptionVerificationContext()) is False


def test_truth_sufficient_keeps_pass():
    from orca.docs.store import DocStore
    from orca.docs.chunker import chunk_text
    store = DocStore(session_id="sim-closure-truth-1")
    store.add_chunks(chunk_text("The rollout window is 15 minutes.", doc_id="d1", filename="f.txt"), doc_id="d1", filename="f.txt")
    a = Assumption(description="the rollout window is 15 minutes", source="plan")
    verified = asyncio.run(verify_assumption(a, simulation_id="sim-1", ctx=AssumptionVerificationContext(externally_factual=True), doc_store=store))
    verdict, warnings = apply_truth_impact_to_verdict(SimulationVerdict.PASS, [verified], is_high_risk=True)
    assert verdict == SimulationVerdict.PASS
    assert warnings == []


def test_truth_conflicted_changes_verdict_to_revise():
    contested = Assumption(description="x", source="truth_fabric_verification", verification_state="CONTESTED")
    verdict, warnings = apply_truth_impact_to_verdict(SimulationVerdict.PASS, [contested], is_high_risk=True)
    assert verdict == SimulationVerdict.REVISE
    assert warnings


def test_truth_insufficient_prevents_high_risk_pass():
    unverified = Assumption(description="x", source="truth_fabric_verification", verification_state="UNVERIFIED")
    verdict, _ = apply_truth_impact_to_verdict(SimulationVerdict.PASS, [unverified], is_high_risk=True)
    assert verdict == SimulationVerdict.INCONCLUSIVE


def test_truth_impact_never_applies_to_non_high_risk():
    contested = Assumption(description="x", source="truth_fabric_verification", verification_state="CONTESTED")
    verdict, warnings = apply_truth_impact_to_verdict(SimulationVerdict.PASS, [contested], is_high_risk=False)
    assert verdict == SimulationVerdict.PASS
    assert warnings == []


# ── §45: fake verified assumption has no effect ───────────────────────────

def test_fake_pre_verified_assumption_is_overwritten_by_real_verification():
    """A model/user fabricating an Assumption already marked VERIFIED
    (never having gone through Truth Fabric) has zero effect once real
    verification runs -- verify_assumption() always computes a FRESH
    state from the real evidence_state, never trusting the input's
    existing verification_state."""
    fake_verified = Assumption(description="the sky is green and gravity reverses on Tuesdays", source="model_hallucination", verification_state="VERIFIED")
    result = asyncio.run(verify_assumption(fake_verified, simulation_id="sim-1", ctx=AssumptionVerificationContext(high_impact=True)))
    assert result.verification_state != "VERIFIED"  # overwritten by the real (failing) check
    assert result.source == "truth_fabric_verification"  # provenance shows it was actually re-checked


# ── §44: Truth cannot issue lease / change tenant / grant capability ─────

def test_truth_verification_module_never_imports_godmode():
    import ast
    tree = ast.parse(Path("orca/simulation/truth_verification.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("orca.godmode"):
            assert False, "truth_verification.py must never import orca.godmode"


def test_truth_impact_never_upgrades_a_block_verdict():
    verified = Assumption(description="x", source="truth_fabric_verification", verification_state="VERIFIED")
    verdict, _ = apply_truth_impact_to_verdict(SimulationVerdict.BLOCK, [verified], is_high_risk=True)
    assert verdict == SimulationVerdict.BLOCK  # a "verified" assumption cannot rescue a BLOCK


# ── §43: branch authority ──────────────────────────────────────────────────

def test_run_bounded_branches_has_no_per_branch_authority_override_params():
    sig = inspect.signature(run_bounded_branches)
    forbidden = {"capabilities", "lease_id", "tenant_id", "budget_override"}
    assert not (set(sig.parameters) & forbidden)


# ── §42: projected state escape via symlink chain ─────────────────────────

def test_projected_symlink_from_root_still_blocks_subsequent_action():
    root = Path(tempfile.mkdtemp())
    secret = Path(tempfile.mkdtemp()) / "secret.txt"
    secret.write_text("real secret")
    (root / "escape_link").symlink_to(secret)

    task_a = AgentTask(description="create unrelated")
    task_b = AgentTask(description="modify escape_link", dependencies=[task_a.task_id])
    action_a = AgentAction(task_id=task_a.task_id, tool_id="write_file", arguments={"operation": "create", "path": "unrelated.txt", "content": "x"})
    action_b = AgentAction(task_id=task_b.task_id, tool_id="write_file", arguments={"operation": "modify", "path": "escape_link", "content": "OVERWRITTEN"})
    plan = AgentPlan(tasks=[task_a, task_b], actions=[action_a, action_b])
    result = simulate_plan(plan, filesystem_root=root)
    assert result.per_action[1].verdict == SimulationVerdict.BLOCK
    assert secret.read_text() == "real secret"


# ── async cancellation ──────────────────────────────────────────────────────

def test_cancel_between_actions_partial_result():
    root = Path(tempfile.mkdtemp())
    plan = _chain_plan(root, 3)

    async def _run():
        t = asyncio.create_task(simulate_plan_async(plan, filesystem_root=root))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        t.cancel()
        return await t

    result = asyncio.run(_run())
    assert result.aggregate_verdict == SimulationVerdict.INCONCLUSIVE
    assert len(result.action_order) < 3
    assert any("cancel" in r.lower() for r in result.block_reasons)


def test_no_orphan_simulation_task_after_cancellation():
    root = Path(tempfile.mkdtemp())
    plan = _chain_plan(root, 3)

    async def _run():
        t = asyncio.create_task(simulate_plan_async(plan, filesystem_root=root))
        await asyncio.sleep(0)
        t.cancel()
        await t
        pending = [task for task in asyncio.all_tasks() if not task.done() and task is not asyncio.current_task()]
        return pending

    pending = asyncio.run(_run())
    assert pending == []


# ── plan RealityDiff halting ───────────────────────────────────────────────

def test_plan_reality_mismatch_flags_remaining_actions_halted():
    from orca.simulation.contracts import PredictedEffect, EffectType
    e1 = PredictedEffect(resource="a.txt", effect_type=EffectType.CREATE, predicted_after_reference="h1")
    obs1 = Observation(action_id="act-1", source="write_file", status="OK", facts=["wrote something totally unrelated"])
    diff = reconcile_plan(plan_simulation_id="plansim-1", per_action_predicted=[("act-1", [e1])], observations={"act-1": obs1})
    assert diff.remaining_actions_halted is True


def test_plan_reality_match_never_halts():
    from orca.simulation.contracts import PredictedEffect, EffectType
    e1 = PredictedEffect(resource="a.txt", effect_type=EffectType.CREATE, predicted_after_reference="h1")
    obs1 = Observation(action_id="act-1", source="write_file", status="OK", facts=["wrote a.txt"])
    diff = reconcile_plan(plan_simulation_id="plansim-1", per_action_predicted=[("act-1", [e1])], observations={"act-1": obs1})
    assert diff.remaining_actions_halted is False
