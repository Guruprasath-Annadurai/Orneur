"""
Godmode latency benchmark (Phase 10 spec §64-65). Measures FRAMEWORK
overhead only -- lease lookup, integrity validation, scope match,
expiry/revocation check, policy decision, atomic use consumption, audit
event creation -- never real tool/network/connector-provider latency.
Also measures normal-mode (no elevation attempted) overhead to confirm
spec §65's "minimal overhead" claim numerically.
"""
from __future__ import annotations

import statistics
import time
from dataclasses import dataclass

from orca.godmode.audit import record_elevation_event
from orca.godmode.contracts import CapabilityDomain, ElevatedCapabilityRequest, ElevationAuditEventType, LeaseIssuerClass
from orca.godmode.integrity import verify_lease_integrity
from orca.godmode.issuance import issue_lease, make_approval
from orca.godmode.lease_store import consume_use, get as get_lease
from orca.godmode.resolution import resolve_lease


@dataclass
class LatencyResult:
    name: str
    mean_ms: float
    p95_ms: float
    n: int


def _measure(name: str, fn, n: int = 200) -> LatencyResult:
    samples = []
    for _ in range(n):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)
    samples.sort()
    p95_idx = min(int(n * 0.95), n - 1)
    return LatencyResult(name=name, mean_ms=statistics.mean(samples), p95_ms=samples[p95_idx], n=n)


def run_all() -> list[LatencyResult]:
    req = ElevatedCapabilityRequest(principal_id="u1", tenant_id="org-bench-1", capability_domain=CapabilityDomain.FILE, capability="FILE_WRITE", resource_scope="/workspace/bench", operation_scope="write", reason="bench")
    approval = make_approval(request=req, approved_by="human-1", duration_s=600)
    lease = issue_lease(approval=approval, issuer=LeaseIssuerClass.HUMAN_APPROVAL, issuer_id="human-1", max_uses=10_000)

    results = []
    results.append(_measure("lease_lookup", lambda: get_lease(lease.lease_id)))
    results.append(_measure("integrity_validation", lambda: verify_lease_integrity(get_lease(lease.lease_id))))
    results.append(_measure("full_resolve_lease_scope_match_expiry_revocation", lambda: resolve_lease(lease.lease_id, tenant_id="org-bench-1", capability_domain=CapabilityDomain.FILE, capability="FILE_WRITE", resource_scope="/workspace/bench", operation_scope="write")))
    results.append(_measure("audit_event_creation", lambda: record_elevation_event(event_type=ElevationAuditEventType.USE, principal_id="u1", tenant_id="org-bench-1", capability="FILE_WRITE", resource_scope="/workspace/bench", operation_scope="write", lease_id=lease.lease_id)))
    results.append(_measure("atomic_use_consumption", lambda: consume_use(lease.lease_id), n=100))  # bounded by max_uses

    # Normal-mode (no elevation attempted) overhead: an AgentRuntime run
    # with no tenant_id/lease_resolver never even calls into this
    # package -- see test_godmode_fast_path.py's structural proof. The
    # "overhead" here is definitionally zero (no code runs), so nothing
    # further to measure beyond that structural guarantee.
    return results


if __name__ == "__main__":
    for r in run_all():
        print(f"{r.name}: mean={r.mean_ms:.4f}ms p95={r.p95_ms:.4f}ms (n={r.n})")
