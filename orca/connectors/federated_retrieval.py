"""
Federated enterprise search (Phase 9 spec §33-34, §61). Queries only
AUTHORIZED connector instances for the requesting tenant -- never "all
connectors on every request" (spec §34's explicit bound). Results retain
per-connector provenance; a partial failure (some connectors succeed,
some don't) is represented honestly, never silently implying exhaustive
coverage (spec §61).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from orca.connectors.contracts import ConnectorIdentity, ConnectorReadRequest, OutcomeStatus
from orca.connectors.policy import evaluate_connector_policy
from orca.connectors.contracts import ConnectorCapabilityKind
from orca.connectors.registry import ConnectorRegistry


@dataclass
class FederatedSearchResult:
    query: str
    results_by_connector: dict[str, list[dict]] = field(default_factory=dict)
    failed_connectors: dict[str, str] = field(default_factory=dict)
    skipped_unhealthy: list[str] = field(default_factory=list)

    @property
    def is_partial(self) -> bool:
        return bool(self.failed_connectors) or bool(self.skipped_unhealthy)


def federated_search(
    identity: ConnectorIdentity, registry: ConnectorRegistry, query: str,
    *, read_fns: dict[str, callable], connector_instance_ids: list[str] | None = None,
) -> FederatedSearchResult:
    """
    `read_fns` maps `connector_type.value -> read_fn(identity, instance, request) -> ConnectorResult`
    for the connector families actually being searched. `connector_instance_ids`,
    when given, bounds the search to that explicit list (spec §34's "bounded
    source planning") -- when omitted, defaults to every instance VISIBLE
    to this tenant (never another tenant's), via `registry.list_for_tenant()`.
    """
    instances = (
        [registry.get_for_tenant(identity.tenant_id, cid) for cid in connector_instance_ids]
        if connector_instance_ids is not None
        else registry.list_for_tenant(identity.tenant_id)
    )

    result = FederatedSearchResult(query=query)
    for instance in instances:
        if not registry.is_routable(instance.connector_instance_id):
            result.skipped_unhealthy.append(instance.connector_instance_id)
            continue
        decision = evaluate_connector_policy(identity=identity, instance=instance, requested_capability=ConnectorCapabilityKind.CONNECTOR_READ)
        if decision.state.value != "ALLOW":
            result.failed_connectors[instance.connector_instance_id] = "; ".join(decision.reasons)
            continue
        read_fn = read_fns.get(instance.connector_type.value)
        if read_fn is None:
            result.failed_connectors[instance.connector_instance_id] = f"no read adapter registered for {instance.connector_type.value}"
            continue
        request = ConnectorReadRequest(identity=identity, connector_instance_id=instance.connector_instance_id, scope=instance.scope, query=query)
        try:
            connector_result = read_fn(identity, instance, request)
        except Exception as e:
            result.failed_connectors[instance.connector_instance_id] = f"{type(e).__name__}: {e}"
            registry.record_failure(instance.connector_instance_id, failure_class="TRANSIENT")
            continue
        if connector_result.status != OutcomeStatus.SUCCESS:
            result.failed_connectors[instance.connector_instance_id] = connector_result.error_class or connector_result.status.value
            continue
        registry.record_success(instance.connector_instance_id)
        result.results_by_connector[instance.connector_instance_id] = connector_result.normalized_content

    return result
