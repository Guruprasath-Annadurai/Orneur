from __future__ import annotations

import threading
import time

import pytest

from orca.specialists.contracts import SpecialistError, TaskNode
from orca.specialists.handlers import HANDLERS
from orca.specialists.orchestrator import Orchestrator
from orca.specialists.registry import REGISTRY_VERSION, SpecialistRegistry
from orca.sovereign_mission.store import digest


TENANT = "user-a"
OTHER = "user-b"


def _caps(*names: str) -> frozenset[str]:
    return frozenset(names)


def test_registry_hides_disabled_roles():
    registry = SpecialistRegistry(enabled=frozenset({"research"}))
    assert registry.roles() == ["research"]
    with pytest.raises(SpecialistError) as exc:
        registry.get("coding")
    assert exc.value.code == "role_unavailable"
    assert registry.version == REGISTRY_VERSION


def test_ten_handlers_are_distinct_and_useful():
    research = HANDLERS["research"]({"tenant_id": TENANT, "query": "What is X; then why Y?"})
    assert research.status == "unavailable"
    assert research.output["invented_sources"] is False
    assert len(research.output["subquestions"]) == 2

    plan = HANDLERS["planning"](
        {"tenant_id": TENANT, "tasks": [{"id": "a"}, {"id": "b", "depends_on": ["a"]}]}
    )
    assert plan.output["order"] == ["a", "b"]

    code = HANDLERS["coding"]({"tenant_id": TENANT, "source": "def add(x, y):\n    return x + y\n"})
    assert code.output["functions"] == ["add"]
    assert code.output["executed"] is False

    stats = HANDLERS["data_analysis"](
        {"tenant_id": TENANT, "column": "n", "rows": [{"n": 1}, {"n": 3}, {"n": 5}]}
    )
    assert stats.output["mean"] == 3
    assert stats.output["median"] == 3

    retrieved = HANDLERS["retrieval"](
        {
            "tenant_id": TENANT,
            "query": "alpha token",
            "documents": [
                {"tenant_id": TENANT, "doc_id": "d1", "text": "alpha token lives here", "locator": 0, "synthetic": True},
                {"tenant_id": OTHER, "doc_id": "secret", "text": "alpha token other tenant", "locator": 0},
            ],
        }
    )
    ids = [row["doc_id"] for row in retrieved.output["citations"]]
    assert ids == ["d1"]
    assert retrieved.synthetic is True

    record = {"step": "marker", "ok": True}
    good = HANDLERS["evidence_verification"](
        {"tenant_id": TENANT, "records": [{"record": record, "record_sha256": digest(record)}]}
    )
    assert good.status == "verified"
    bad = HANDLERS["evidence_verification"](
        {"tenant_id": TENANT, "records": [{"record": record, "record_sha256": "0" * 64}]}
    )
    assert bad.status == "unverified"

    security = HANDLERS["security_analysis"](
        {"tenant_id": TENANT, "text": "key AKIAIOSFODNN7EXAMPLE and http://169.254.169.254/latest"}
    )
    kinds = {item["kind"] for item in security.output["findings"]}
    assert "secret" in kinds
    assert "ssrf_host" in kinds

    docs = HANDLERS["documentation"](
        {"tenant_id": TENANT, "source": 'def ping(x):\n    """Return x."""\n    return x\n'}
    )
    assert docs.output["pages"][0]["name"] == "ping"
    assert "Return x." in docs.output["pages"][0]["doc"]

    hashed = HANDLERS["tool_execution"]({"tenant_id": TENANT, "tool": "sha256", "input": "abc"})
    assert hashed.output["result"]["digest"] == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    with pytest.raises(SpecialistError) as exc:
        HANDLERS["tool_execution"]({"tenant_id": TENANT, "tool": "shell", "input": "ls"})
    assert exc.value.code == "tool_refused"

    inspect = HANDLERS["mission_coordination"](
        {"tenant_id": TENANT, "mission": {"state": "OUTCOME_UNKNOWN", "owner_user_id": TENANT, "claim": "verified", "steps": []}}
    )
    assert inspect.status == "refused"
    assert inspect.output["dispatched"] is False


def test_coding_refuses_eval_and_does_not_run_it():
    result = HANDLERS["coding"]({"tenant_id": TENANT, "source": "eval('os.system')\n"})
    assert result.status == "refused"
    assert result.output["executed"] is False
    assert "eval" in result.output["dangerous_calls"]


def test_planning_refuses_cycles():
    with pytest.raises(SpecialistError) as exc:
        HANDLERS["planning"](
            {"tenant_id": TENANT, "tasks": [{"id": "a", "depends_on": ["b"]}, {"id": "b", "depends_on": ["a"]}]}
        )
    assert exc.value.code == "cycle_refused"


def test_orchestrator_orders_and_aggregates_evidence():
    orch = Orchestrator(
        tenant_id=TENANT,
        capabilities=_caps("plan.write", "code.read", "docs.write"),
        max_workers=2,
    )
    body = orch.run(
        [
            TaskNode("plan", "planning", {"tasks": [{"id": "one"}, {"id": "two", "depends_on": ["one"]}]}, capabilities=_caps("plan.write")),
            TaskNode(
                "code",
                "coding",
                {"source": "def one():\n    return 1\n"},
                depends_on=("plan",),
                capabilities=_caps("code.read"),
            ),
            TaskNode(
                "docs",
                "documentation",
                {"source": "def one():\n    '''n'''\n    return 1\n"},
                depends_on=("code",),
                capabilities=_caps("docs.write"),
            ),
        ]
    )
    assert body["results"]["plan"]["output"]["order"] == ["one", "two"]
    assert body["results"]["code"]["output"]["functions"] == ["one"]
    assert body["results"]["docs"]["output"]["count"] == 1
    assert body["errors"] == {}
    assert body["evidence_sha256"]


def test_orchestrator_blocks_privilege_escalation_and_cross_tenant():
    orch = Orchestrator(tenant_id=TENANT, capabilities=_caps("code.read"))
    with pytest.raises(SpecialistError) as exc:
        orch.run([TaskNode("sec", "security_analysis", {"text": "x"}, capabilities=_caps("security.read"))])
    assert exc.value.code == "privilege_escalation"
    with pytest.raises(SpecialistError) as exc:
        orch.run([TaskNode("code", "coding", {"tenant_id": OTHER, "source": "x = 1\n"}, capabilities=_caps("code.read"))])
    assert exc.value.code == "tenant_mismatch"


def test_orchestrator_cancel_and_unknown_irreversible():
    orch = Orchestrator(tenant_id=TENANT, capabilities=_caps("tool.hash"), max_workers=1)
    orch.cancel()
    with pytest.raises(SpecialistError) as exc:
        orch.run([TaskNode("h", "tool_execution", {"tool": "sha256", "input": "z"}, capabilities=_caps("tool.hash"))])
    assert exc.value.code == "cancelled"

    orch2 = Orchestrator(tenant_id=TENANT, capabilities=_caps("tool.hash"))
    body = orch2.run(
        [TaskNode("fx", "tool_execution", {"tool": "sha256", "input": "z"}, capabilities=_caps("tool.hash"), irreversible=True)]
    )
    assert body["results"]["fx"]["status"] == "unknown"
    assert body["errors"]["fx"] == "outcome_unknown"


def test_handlers_require_tenant():
    with pytest.raises(SpecialistError) as exc:
        HANDLERS["research"]({"query": "x"})
    assert exc.value.code == "tenant_required"


def test_cancel_during_dispatch_is_observed():
    started = threading.Event()
    orch = Orchestrator(tenant_id=TENANT, capabilities=_caps("data.read"), max_workers=1, deadline_s=2)

    class SlowNode(TaskNode):
        pass

    original = HANDLERS["data_analysis"]

    def wrapped(payload):
        started.set()
        while not orch._cancel.is_set():
            time.sleep(0.01)
        raise SpecialistError("cancelled")

    from orca.specialists import handlers as handlers_mod

    handlers_mod.HANDLERS["data_analysis"] = wrapped
    try:
        def stop():
            started.wait(1)
            orch.cancel()

        stopper = threading.Thread(target=stop)
        stopper.start()
        with pytest.raises(SpecialistError) as exc:
            orch.run(
                [
                    TaskNode(
                        "stats",
                        "data_analysis",
                        {"column": "n", "rows": [{"n": 1}] * 3},
                        capabilities=_caps("data.read"),
                    )
                ]
            )
        stopper.join()
        assert exc.value.code == "cancelled"
    finally:
        handlers_mod.HANDLERS["data_analysis"] = original
