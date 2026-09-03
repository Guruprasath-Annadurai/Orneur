"""
Godmode <-> Simulation integration (Phase 11 spec §47-51). Two
disciplines, both enforced structurally here rather than left as a
convention callers might forget:

1. Simulation NEVER consumes a one-use lease (see `chamber.py`'s
   `_check_lease_compatibility()`, which calls the READ-ONLY
   `orca.godmode.resolution.resolve_lease()`, never
   `resolve_and_consume_lease()`). The lease is revalidated AND consumed
   only here, immediately before the real action executes.
2. Lease state (expiry/revocation/kill switch) and resource state
   (fingerprint) can both change between simulation and execution --
   `revalidate_and_consume_before_execution()` re-checks the lease fresh
   (spec §48: "simulation does not lock authority"), and
   `check_simulation_staleness()` re-checks the resource fingerprint
   (spec §49-51) -- both immediately before the real call, never relying
   on what simulation observed minutes earlier.
"""
from __future__ import annotations

from dataclasses import dataclass

from orca.godmode.contracts import CapabilityDomain, ElevatedPolicyDecision
from orca.godmode.resolution import resolve_and_consume_lease
from orca.simulation.contracts import StateFingerprint
from orca.simulation.fingerprint import is_stale


def revalidate_and_consume_before_execution(
    *, lease_id: str, tenant_id: str, capability_domain: CapabilityDomain, capability: str,
    resource_scope: str, operation_scope: str, arguments: dict,
) -> ElevatedPolicyDecision:
    """
    The ONE place a lease is actually consumed for a simulated-then-
    executed elevated action. Called IMMEDIATELY before the real
    tool/connector call -- never earlier, and never reused across
    multiple real calls from one simulation (a lease revoked, expired,
    exhausted, or kill-switched between simulation and this call is
    denied HERE, fresh, regardless of what the simulation itself found).
    """
    return resolve_and_consume_lease(
        lease_id, tenant_id=tenant_id, capability_domain=capability_domain, capability=capability,
        resource_scope=resource_scope, operation_scope=operation_scope, arguments=arguments,
    )


@dataclass
class StalenessCheckResult:
    stale: bool
    reason: str


def check_simulation_staleness(*, simulated_fingerprint: StateFingerprint, current_fingerprint: StateFingerprint) -> StalenessCheckResult:
    """
    spec §49-51: if the resource's real current state no longer matches
    what was fingerprinted at simulation time, the simulation is STALE
    and policy should require re-simulation/review rather than executing
    under a prediction made against different underlying state.
    Fingerprinting-unavailable resources cannot be checked at all --
    `is_stale()` returns False for that pairing, and the caller is told
    explicitly staleness could not be determined (never silently assumed
    fresh, per `fingerprint.py`'s own documented honesty).
    """
    from orca.simulation.fingerprint import fingerprinting_available
    if not fingerprinting_available(simulated_fingerprint) or not fingerprinting_available(current_fingerprint):
        return StalenessCheckResult(stale=False, reason="fingerprinting unavailable for this resource -- staleness could not be determined")
    if is_stale(simulated_fingerprint, current_fingerprint):
        return StalenessCheckResult(stale=True, reason=f"resource '{simulated_fingerprint.resource}' state changed since simulation ({simulated_fingerprint.value} -> {current_fingerprint.value})")
    return StalenessCheckResult(stale=False, reason="resource state unchanged since simulation")
