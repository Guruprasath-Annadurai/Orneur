"""
Connector registry (Phase 9 spec §5, §7, §19-20). Holds `ConnectorInstance`
records, indexed by tenant -- lookup by `(tenant_id, connector_instance_id)`
is the ONLY lookup path, so a tenant can never even ENUMERATE another
tenant's connector instances, let alone read/act on them (spec §7's
critical invariant, enforced at the lookup layer, not just the policy
layer -- defense in depth).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from orca.connectors.contracts import ConnectorHealth, ConnectorHealthState, ConnectorInstance

# Bounded circuit breaker (spec §20) -- differentiate failure classes;
# never retry indefinitely.
_CIRCUIT_FAILURE_THRESHOLD = 5


class TenantIsolationError(ValueError):
    """Raised the instant a lookup would cross a tenant boundary -- never
    silently returns None (which could be mistaken for 'not found' rather
    than 'not yours')."""


@dataclass
class ConnectorRegistry:
    _instances: dict[str, ConnectorInstance] = field(default_factory=dict)
    _health: dict[str, ConnectorHealth] = field(default_factory=dict)

    def register(self, instance: ConnectorInstance) -> None:
        self._instances[instance.connector_instance_id] = instance
        self._health[instance.connector_instance_id] = ConnectorHealth(connector_instance_id=instance.connector_instance_id)

    def get_for_tenant(self, tenant_id: str, connector_instance_id: str) -> ConnectorInstance:
        """The ONLY lookup method -- requires the caller's OWN tenant_id
        explicitly. Raises TenantIsolationError (never returns another
        tenant's instance, never returns None ambiguously) if the
        instance belongs to a different tenant or doesn't exist."""
        instance = self._instances.get(connector_instance_id)
        if instance is None or instance.tenant_id != tenant_id:
            raise TenantIsolationError(f"no connector instance '{connector_instance_id}' visible to tenant '{tenant_id}'")
        return instance

    def list_for_tenant(self, tenant_id: str) -> list[ConnectorInstance]:
        """Never returns another tenant's instances -- filtered strictly."""
        return [i for i in self._instances.values() if i.tenant_id == tenant_id]

    def health_for(self, connector_instance_id: str) -> ConnectorHealth:
        return self._health.get(connector_instance_id, ConnectorHealth(connector_instance_id=connector_instance_id))

    def record_success(self, connector_instance_id: str) -> None:
        health = self.health_for(connector_instance_id)
        health.consecutive_failures = 0
        health.state = ConnectorHealthState.HEALTHY
        self._health[connector_instance_id] = health

    def record_failure(self, connector_instance_id: str, *, failure_class: str = "TRANSIENT") -> None:
        """Differentiates failure classes (spec §20) -- an AUTH_FAILURE
        or POLICY_DENIAL never opens/counts toward the transient-failure
        circuit breaker the same way a network TIMEOUT does; those are
        deterministic outcomes a retry would never fix."""
        health = self.health_for(connector_instance_id)
        if failure_class == "AUTH_FAILURE":
            health.state = ConnectorHealthState.UNAUTHORIZED
        elif failure_class == "RATE_LIMIT":
            health.state = ConnectorHealthState.RATE_LIMITED
        elif failure_class == "TRANSIENT":
            health.consecutive_failures += 1
            if health.consecutive_failures >= _CIRCUIT_FAILURE_THRESHOLD:
                health.state = ConnectorHealthState.OFFLINE
        self._health[connector_instance_id] = health

    def is_routable(self, connector_instance_id: str) -> bool:
        """Never continuously send traffic to a known-broken connector
        (spec §19)."""
        health = self.health_for(connector_instance_id)
        return health.state in (ConnectorHealthState.HEALTHY, ConnectorHealthState.DEGRADED)
