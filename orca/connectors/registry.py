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
from datetime import datetime, timezone

from orca.connectors.contracts import ConnectorHealth, ConnectorHealthState, ConnectorInstance
from orca.connectors.contracts import _now_iso

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

    def record_failure(self, connector_instance_id: str, *, failure_class: str = "TRANSIENT", retry_after_s: float | None = None) -> None:
        """Differentiates failure classes (spec §20) -- an AUTH_FAILURE
        or POLICY_DENIAL never opens/counts toward the transient-failure
        circuit breaker the same way a network TIMEOUT does; those are
        deterministic outcomes a retry would never fix.

        `retry_after_s` (Phase 9.1 spec §19), when the failing provider
        supplied one (e.g. an HTTP `Retry-After` header), is recorded on
        the health record -- `retry_after_remaining()` exposes it so a
        caller never retries a RATE_LIMITED connector before the
        provider's own cooldown has elapsed, instead of retrying
        immediately or blindly on a fixed interval."""
        health = self.health_for(connector_instance_id)
        if failure_class == "AUTH_FAILURE":
            health.state = ConnectorHealthState.UNAUTHORIZED
        elif failure_class == "RATE_LIMIT":
            health.state = ConnectorHealthState.RATE_LIMITED
            health.retry_after_s = retry_after_s
            health.last_checked_at = _now_iso()
        elif failure_class == "TRANSIENT":
            health.consecutive_failures += 1
            if health.consecutive_failures >= _CIRCUIT_FAILURE_THRESHOLD:
                health.state = ConnectorHealthState.OFFLINE
        self._health[connector_instance_id] = health

    def is_routable(self, connector_instance_id: str) -> bool:
        """Never continuously send traffic to a known-broken connector
        (spec §19). A RATE_LIMITED connector whose provider-supplied
        `retry_after_s` window has genuinely elapsed becomes routable
        again automatically -- one whose window has not elapsed, or
        which never supplied one, stays unroutable rather than being
        retried on a guess."""
        health = self.health_for(connector_instance_id)
        if health.state == ConnectorHealthState.RATE_LIMITED:
            return self._retry_after_elapsed(health)
        return health.state in (ConnectorHealthState.HEALTHY, ConnectorHealthState.DEGRADED)

    def _retry_after_elapsed(self, health: ConnectorHealth) -> bool:
        if health.retry_after_s is None:
            return False
        try:
            checked_at = datetime.strptime(health.last_checked_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            return False
        return (datetime.now(timezone.utc) - checked_at).total_seconds() >= health.retry_after_s

    def retry_after_remaining(self, connector_instance_id: str) -> float | None:
        """Seconds remaining before a RATE_LIMITED connector's own
        provider-supplied cooldown elapses, or None if not rate-limited
        or no cooldown was ever supplied."""
        health = self.health_for(connector_instance_id)
        if health.state != ConnectorHealthState.RATE_LIMITED or health.retry_after_s is None:
            return None
        try:
            checked_at = datetime.strptime(health.last_checked_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
        remaining = health.retry_after_s - (datetime.now(timezone.utc) - checked_at).total_seconds()
        return max(0.0, remaining)
