"""Versioned synthetic tasks. Deterministic handlers are not model scores."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from orca.pretrain_foundation.agents import (
    AgentIdentity,
    BudgetExhausted,
    Orchestrator,
    PermissionDenied,
    QueueSaturated,
    TaskSpec,
)
from orca.pretrain_foundation.capability_contracts import CAPABILITIES
from orca.pretrain_foundation.capability_graph import CapabilityGraph
from orca.pretrain_foundation.failure_genome import FailureGenome, FailureGenomeError
from orca.pretrain_foundation.governed_handlers import HANDLERS
from orca.pretrain_foundation.synthetic_suite import SUITE_VERSION, run_synthetic_suite, shadow_tournament

LEDGER = Path("docs/orneur/acceptance/acceptance_ledger.json")
LEDGER_SHA256 = "37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570"


def _by_id(report: dict) -> dict:
    return {task["id"]: task for task in report["tasks"]}


def test_suite_selects_the_smallest_team_that_meets_the_predicate():
    report = run_synthetic_suite(trials=5)
    assert report["version"] == SUITE_VERSION
    assert report["model_inference"] is False
    assert report["independently_qualified"] is False
    assert report["production_authorized"] is False
    assert report["latency_unit"] == "process_perf_counter_seconds"
    tasks = _by_id(report)
    assert tasks["reasoning-unsupported"]["selected_team_size"] == 2
    assert tasks["reasoning-unsupported"]["larger_team_justified"] is True
    unsupported = tasks["reasoning-unsupported"]["sizes"]
    assert unsupported["1"]["success"] is False
    assert unsupported["1"]["unsupported_claims"] == 1
    assert unsupported["2"]["success"] is True
    assert unsupported["10"]["success"] is True
    assert unsupported["10"]["false_verification"] == 0
    assert unsupported["10"]["resource_handler_calls"] > unsupported["2"]["resource_handler_calls"]
    assert tasks["reasoning-supported"]["selected_team_size"] == 1
    assert tasks["reasoning-supported"]["larger_team_justified"] is False
    assert tasks["coding-return-value"]["selected_team_size"] is None
    assert tasks["retrieval-span"]["selected_team_size"] is None
    assert tasks["contradiction"]["selected_team_size"] == 2
    assert tasks["contradiction"]["sizes"]["3"]["failure_recovery"] == 1
    assert tasks["contradiction"]["sizes"]["3"]["contained_handler_errors"] == 1
    assert tasks["abstention"]["selected_team_size"] == 1
    assert tasks["authority-refusal"]["selected_team_size"] == 1
    assert tasks["authority-refusal"]["sizes"]["1"]["false_verification"] == 0
    assert tasks["workflow-incomplete"]["selected_team_size"] == 1
    for task in report["tasks"]:
        for row in task["sizes"].values():
            assert row["variance"] == 0
            assert row["false_verification"] == 0
            assert row["latency_seconds"] >= 0
            assert row["trial_successes"] == [row["success"]] * 5
    with pytest.raises(ValueError, match="at least 2"):
        run_synthetic_suite(trials=1)


def test_shadow_tournament_does_not_promote_a_winner():
    report = run_synthetic_suite(trials=2)
    ranked = shadow_tournament(report)
    assert ranked["qualified"] is False
    assert ranked["production_authorized"] is False
    assert ranked["tasks"]["reasoning-unsupported"]["selected_team_size"] == 2
    assert ranked["tasks"]["reasoning-unsupported"]["qualified"] is False
    with pytest.raises(ValueError, match="synthetic-agent-eval-v1"):
        shadow_tournament({"version": "other", "tasks": []})


def test_capability_graph_blocks_despite_a_qualified_advertisement():
    graph = CapabilityGraph()
    graph.block("claim.falsify", "fixture block")
    selected = HANDLERS["team.select"](
        {"tasks": ["claim.falsify", "team.select"], "qualified": True, "production_authorized": True},
        {"capability_graph": graph},
    )
    assert selected["advertisement_trusted"] is False
    assert graph.advertisement_trusted({"qualified": True}) is False
    assert "claim.falsify" in selected["blocked_unqualified"]
    assert selected["selected_count"] == 1
    assert graph.version == "capability-graph-v1"


def test_failure_genome_refuses_self_closure_and_duplicate_ids():
    genome = FailureGenome()
    opened = genome.record(failure_id="f1", observed="size 1 left the false equation observed", produced_by="suite")
    assert opened["resolution"] == "OPEN"
    with pytest.raises(FailureGenomeError, match="duplicate"):
        genome.record(failure_id="f1", observed="again", produced_by="suite")
    with pytest.raises(FailureGenomeError, match="producer"):
        genome.resolve("f1", decided_by="suite", regression_test_id="test_synthetic_agent_eval")
    with pytest.raises(FailureGenomeError, match="regression"):
        genome.resolve("f1", decided_by="reviewer", regression_test_id="")
    closed = genome.resolve("f1", decided_by="reviewer", regression_test_id="test_synthetic_agent_eval")
    assert closed["resolution"] == "RESOLVED_PENDING_INDEPENDENT_REVIEW"
    assert closed["digest"] == opened["digest"]


def test_budget_queue_and_child_budget_stay_bounded():
    budget = Orchestrator(max_concurrent=1, queue_bound=4)
    budget.register_agent(AgentIdentity("root", None, frozenset({"governed"}), 1))
    budget.register_handler("noop", lambda _payload, _ctx: {"ok": True}, "governed")
    budget.submit(TaskSpec("one", "root", "noop", {}, "budget-1", cost_units=1))
    with pytest.raises(BudgetExhausted):
        budget.submit(TaskSpec("two", "root", "noop", {}, "budget-2", cost_units=1))
    queue = Orchestrator(max_concurrent=1, queue_bound=1)
    queue.register_agent(AgentIdentity("root", None, frozenset({"governed"}), 10))
    queue.register_handler("noop", lambda _payload, _ctx: {"ok": True}, "governed")
    queue.submit(TaskSpec("one", "root", "noop", {}, "queue-1", cost_units=1))
    with pytest.raises(QueueSaturated):
        queue.submit(TaskSpec("two", "root", "noop", {}, "queue-2", cost_units=1))
    parent = Orchestrator(max_concurrent=1, queue_bound=4)
    parent.register_agent(AgentIdentity("root", None, frozenset({"governed"}), 2))
    with pytest.raises(PermissionDenied, match="child budget"):
        parent.register_agent(AgentIdentity("child", "root", frozenset({"governed"}), 3))


def test_new_synthetic_capabilities_are_not_qualified_and_the_ledger_is_unchanged():
    counts = {}
    for _cap_id, status, _impl in CAPABILITIES:
        counts[status] = counts.get(status, 0) + 1
    assert counts["IMPLEMENTED_SYNTHETIC"] == 17
    assert counts["DESIGNED"] == 18
    assert "INDEPENDENTLY_QUALIFIED" not in counts
    assert "PRODUCTION_AUTHORIZED" not in counts
    raw = LEDGER.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == LEDGER_SHA256
    assert raw == b"[]\n"
