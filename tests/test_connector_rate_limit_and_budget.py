"""
Phase 9.1 spec §19 (rate limiting) and §27 (budget accounting)
regressions.
"""
from __future__ import annotations

import time

from orca.agent.contracts import AgentAction, AgentGoal, AgentPlan, AgentTask, Capability, SideEffectClass
from orca.agent.runtime import AgentRuntime
from orca.agent.tool_registry import AgentToolRegistry
from orca.cognitive.contracts import CognitiveBudget
from orca.connectors.agent_bridge import authorized_connector_tool_specs, make_connector_read_fn
from orca.connectors.contracts import ConnectorCapabilityKind, ConnectorIdentity, ConnectorInstance, ConnectorResult, ConnectorType, OutcomeStatus
from orca.connectors.registry import ConnectorRegistry


def test_rate_limited_connector_unroutable_until_retry_after_elapses():
    """spec §19: a Retry-After-bearing rate limit is honored -- the
    connector is not retried before the provider's own cooldown window,
    and becomes routable again once it genuinely elapses (never on a
    blind fixed-interval guess)."""
    registry = ConnectorRegistry()
    instance = ConnectorInstance(connector_type=ConnectorType.TICKETING, tenant_id="org-1", owner_principal_id="u1")
    registry.register(instance)

    registry.record_failure(instance.connector_instance_id, failure_class="RATE_LIMIT", retry_after_s=1.0)
    assert not registry.is_routable(instance.connector_instance_id)
    assert registry.retry_after_remaining(instance.connector_instance_id) is not None

    time.sleep(1.2)
    assert registry.is_routable(instance.connector_instance_id)


def test_rate_limited_connector_without_retry_after_stays_unroutable():
    """No provider-supplied cooldown means no guessed recovery time --
    stays unroutable until a success is recorded (never retried blindly)."""
    registry = ConnectorRegistry()
    instance = ConnectorInstance(connector_type=ConnectorType.TICKETING, tenant_id="org-1", owner_principal_id="u1")
    registry.register(instance)
    registry.record_failure(instance.connector_instance_id, failure_class="RATE_LIMIT")
    assert registry.retry_after_remaining(instance.connector_instance_id) is None
    assert not registry.is_routable(instance.connector_instance_id)
    time.sleep(0.2)
    assert not registry.is_routable(instance.connector_instance_id)


def test_connector_action_accounted_exactly_once_in_tool_execution_budget():
    """spec §27: a connector read consumes exactly one `tool_execution`
    budget reservation -- never unaccounted, never double-counted, even
    across the runtime's own bounded transient-error retry."""
    connector_registry = ConnectorRegistry()
    instance = ConnectorInstance(
        connector_type=ConnectorType.DOCUMENT_STORE, tenant_id="org-budget-1", owner_principal_id="u1",
        enabled_capabilities=frozenset({ConnectorCapabilityKind.CONNECTOR_READ}),
    )
    connector_registry.register(instance)
    identity = ConnectorIdentity(tenant_id="org-budget-1", principal_id="u1")

    calls = {"n": 0}

    def _counting_read(identity, instance, request):
        calls["n"] += 1
        return ConnectorResult(status=OutcomeStatus.SUCCESS, normalized_content=[{"text": "ok"}])

    tool_specs = authorized_connector_tool_specs(connector_registry, identity)
    tool_id, spec = next(iter(tool_specs.items()))
    tool_registry = AgentToolRegistry()
    tool_registry.register(spec, make_connector_read_fn(connector_registry, identity, instance.connector_instance_id, _counting_read))

    goal = AgentGoal(objective="read once", allowed_action_classes=frozenset({SideEffectClass.READ_ONLY}))
    task = AgentTask(description="read")
    action = AgentAction(task_id=task.task_id, tool_id=tool_id, arguments={"query": "q"}, expected_side_effect=SideEffectClass.READ_ONLY)
    plan = AgentPlan(tasks=[task], actions=[action])

    budget = CognitiveBudget(max_model_calls=10, max_tool_calls=5, max_retrieval_calls=5)
    runtime = AgentRuntime(registry=tool_registry, goal=goal, capabilities=frozenset({Capability.CONNECTOR_READ}), budget=budget)
    remaining_before = runtime.ledger.remaining_for("tool_execution")
    run, trace, world_state = runtime.execute(plan)
    remaining_after = runtime.ledger.remaining_for("tool_execution")

    assert calls["n"] == 1
    # exactly one tool_execution unit consumed for this single connector action
    assert remaining_before - remaining_after == 1
