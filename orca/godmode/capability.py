"""
Effective capability computation (Phase 10 spec §17-18). Computes
`normal_capabilities + valid_lease_grants` WITHOUT modifying
`orca.agent.capability.check_capabilities()` (kept exactly as-is --
Phase 8's own invariant, "an agent's capability set is fixed for the
duration of its run," is preserved: what changes here is which set gets
passed into that unchanged, pure function for one specific action, never
a mutation of the run's base granted set itself).

The caller can never inject an effective capability list directly (spec
§18) -- the only way a capability enters the effective set is by
resolving through a REAL, named, valid lease via `resolve_lease()`. There
is no parameter on `compute_effective_capabilities()` that accepts a bare
`frozenset[Capability]` "extra grants" override.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from orca.agent.contracts import Capability
from orca.godmode.contracts import CapabilityDomain
from orca.godmode.lease_store import get as get_lease
from orca.godmode.resolution import resolve_lease


@dataclass
class EffectiveCapabilityResult:
    effective: frozenset[Capability]
    granted_by_lease: dict[Capability, str] = field(default_factory=dict)   # capability -> lease_id provenance


def compute_effective_capabilities(
    *,
    base_granted: frozenset[Capability],
    tenant_id: str,
    lease_ids: tuple[str, ...] = (),
    resource_scope: str = "",
    operation_scope: str = "",
) -> EffectiveCapabilityResult:
    """
    Resolves each named `lease_id` against the EXACT resource/operation
    the caller is about to attempt -- a lease that does not scope-match
    contributes nothing (fails closed per-lease, never partially widens
    based on an unrelated lease the caller happened to also hold).
    """
    effective = set(base_granted)
    provenance: dict[Capability, str] = {}

    for lease_id in lease_ids:
        lease = get_lease(lease_id)
        if lease is None or lease.capability_domain != CapabilityDomain.AGENT:
            continue
        try:
            capability = Capability(lease.capability)
        except ValueError:
            continue  # lease names a capability value this Capability Engine doesn't know -- never guess
        if capability in effective:
            continue
        decision = resolve_lease(
            lease_id, tenant_id=tenant_id, capability_domain=CapabilityDomain.AGENT,
            capability=capability.value, resource_scope=resource_scope, operation_scope=operation_scope,
        )
        if decision.state.value == "ALLOW":
            effective.add(capability)
            provenance[capability] = lease_id

    return EffectiveCapabilityResult(effective=frozenset(effective), granted_by_lease=provenance)
