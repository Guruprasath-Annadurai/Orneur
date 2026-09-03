"""
Full chain: AgentGoal -> AgentPlan -> AgentRuntime -> Capability -> Policy
-> connector adapter -> DocStore -> Observation -> WorldState (spec §10,
§39-40, §66). Also covers cancellation during a connector read.
"""
from __future__ import annotations

import asyncio

from orca.agent.contracts import (
    AgentAction,
    AgentGoal,
    AgentPlan,
    AgentRunStatus,
    AgentTask,
    Capability,
    SideEffectClass,
)
from orca.agent.runtime import AgentRuntime
from orca.agent.tool_registry import AgentToolRegistry
from orca.connectors.agent_bridge import authorized_connector_tool_specs, make_connector_read_fn
from orca.connectors.contracts import ConnectorCapabilityKind, ConnectorIdentity, ConnectorInstance, ConnectorScope, ConnectorType
from orca.connectors.document_store import _scoped_session_id, search_documents
from orca.connectors.registry import ConnectorRegistry


def _setup(tenant_id="org-e2e-1"):
    connector_registry = ConnectorRegistry()
    instance = ConnectorInstance(
        connector_type=ConnectorType.DOCUMENT_STORE, tenant_id=tenant_id, owner_principal_id="u1",
        enabled_capabilities=frozenset({ConnectorCapabilityKind.CONNECTOR_READ}), scope=ConnectorScope(resource_path="docs"),
    )
    connector_registry.register(instance)
    identity = ConnectorIdentity(tenant_id=tenant_id, principal_id="u1")

    from orca.docs.chunker import chunk_text
    from orca.docs.store import DocStore
    store = DocStore(session_id=_scoped_session_id(instance))
    chunks = chunk_text("The board approved a $12 million budget for Project Falcon.", doc_id="board-minutes", filename="board-minutes.txt")
    store.add_chunks(chunks, doc_id="board-minutes", filename="board-minutes.txt")

    tool_specs = authorized_connector_tool_specs(connector_registry, identity)
    assert len(tool_specs) == 1
    tool_id, spec = next(iter(tool_specs.items()))

    tool_registry = AgentToolRegistry()
    tool_registry.register(spec, make_connector_read_fn(connector_registry, identity, instance.connector_instance_id, search_documents))
    return tool_registry, tool_id, instance, connector_registry, identity


def test_agent_runtime_completes_real_connector_read_end_to_end():
    tool_registry, tool_id, instance, connector_registry, identity = _setup()

    goal = AgentGoal(objective="find the Project Falcon budget", allowed_action_classes=frozenset({SideEffectClass.READ_ONLY}))
    task = AgentTask(description="search enterprise documents")
    action = AgentAction(task_id=task.task_id, tool_id=tool_id, arguments={"query": "Project Falcon budget"}, expected_side_effect=SideEffectClass.READ_ONLY)
    plan = AgentPlan(tasks=[task], actions=[action])

    runtime = AgentRuntime(registry=tool_registry, goal=goal, capabilities=frozenset({Capability.CONNECTOR_READ}))
    run, trace, world_state = runtime.execute(plan)

    assert run.status == AgentRunStatus.COMPLETED
    assert any("12 million" in fact or "Falcon" in fact for fact in world_state.known_facts)


def test_agent_runtime_denies_connector_read_without_capability():
    tool_registry, tool_id, instance, connector_registry, identity = _setup(tenant_id="org-e2e-2")

    goal = AgentGoal(objective="find something", allowed_action_classes=frozenset({SideEffectClass.READ_ONLY}))
    task = AgentTask(description="search")
    action = AgentAction(task_id=task.task_id, tool_id=tool_id, arguments={"query": "anything"}, expected_side_effect=SideEffectClass.READ_ONLY)
    plan = AgentPlan(tasks=[task], actions=[action])

    runtime = AgentRuntime(registry=tool_registry, goal=goal, capabilities=frozenset())  # no CONNECTOR_READ granted
    run, trace, world_state = runtime.execute(plan)

    assert run.status != AgentRunStatus.COMPLETED


def test_cancellation_during_connector_read_returns_structured_cancelled_status():
    """spec §66: cancelling an in-flight connector read must not raise
    out of execute_async() -- it returns a normal CANCELLED status."""
    tool_registry, tool_id, instance, connector_registry, identity = _setup(tenant_id="org-e2e-3")

    def _slow_read(identity, instance, request):
        import time
        time.sleep(0.5)
        return search_documents(identity, instance, request)

    slow_tool_id = f"connector_{instance.connector_instance_id}_slow"
    from orca.connectors.agent_bridge import connector_tool_spec
    spec = connector_tool_spec(instance, tool_id=slow_tool_id)
    tool_registry.register(spec, make_connector_read_fn(connector_registry, identity, instance.connector_instance_id, _slow_read))

    goal = AgentGoal(objective="slow search", allowed_action_classes=frozenset({SideEffectClass.READ_ONLY}))
    task = AgentTask(description="slow connector read")
    action = AgentAction(task_id=task.task_id, tool_id=slow_tool_id, arguments={"query": "Falcon"}, expected_side_effect=SideEffectClass.READ_ONLY)
    plan = AgentPlan(tasks=[task], actions=[action])
    runtime = AgentRuntime(registry=tool_registry, goal=goal, capabilities=frozenset({Capability.CONNECTOR_READ}))

    async def _run_and_cancel():
        run_task = asyncio.create_task(runtime.execute_async(plan))
        await asyncio.sleep(0.05)
        run_task.cancel()
        return await run_task

    run, trace, world_state = asyncio.run(_run_and_cancel())
    assert run.status == AgentRunStatus.CANCELLED
