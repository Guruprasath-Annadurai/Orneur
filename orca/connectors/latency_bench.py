"""
Connector Fabric latency benchmark (Phase 9 spec §68). Measures FRAMEWORK
overhead only -- connector lookup, identity/scope check, policy decision,
result normalization, audit event creation, federated-search planning --
never real provider network latency (the FAKE_TEST_PROVIDER and an
already-populated in-process DocStore are used deliberately so no
network call is on the measured path).
"""
from __future__ import annotations

import statistics
import time
from dataclasses import dataclass

from orca.connectors.audit import record_audit_event, reset_audit_log_for_tests
from orca.connectors.contracts import ConnectorCapabilityKind, ConnectorIdentity, ConnectorInstance, ConnectorReadRequest, ConnectorType
from orca.connectors.document_store import _scoped_session_id, search_documents
from orca.connectors.federated_retrieval import federated_search
from orca.connectors.policy import evaluate_connector_policy
from orca.connectors.registry import ConnectorRegistry


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
    reset_audit_log_for_tests()
    registry = ConnectorRegistry()
    instance = ConnectorInstance(
        connector_type=ConnectorType.DOCUMENT_STORE, tenant_id="org-bench-1", owner_principal_id="u1",
        enabled_capabilities=frozenset({ConnectorCapabilityKind.CONNECTOR_READ}),
    )
    registry.register(instance)
    identity = ConnectorIdentity(tenant_id="org-bench-1", principal_id="u1")

    from orca.docs.chunker import chunk_text
    from orca.docs.store import DocStore
    store = DocStore(session_id=_scoped_session_id(instance))
    store.add_chunks(chunk_text("Latency benchmark seed document.", doc_id="bench-doc", filename="bench.txt"), doc_id="bench-doc", filename="bench.txt")

    results = []
    results.append(_measure("connector_lookup", lambda: registry.get_for_tenant("org-bench-1", instance.connector_instance_id)))
    results.append(_measure("policy_decision", lambda: evaluate_connector_policy(identity=identity, instance=instance, requested_capability=ConnectorCapabilityKind.CONNECTOR_READ)))
    results.append(_measure("is_routable_check", lambda: registry.is_routable(instance.connector_instance_id)))
    results.append(_measure("audit_event_creation", lambda: record_audit_event(identity=identity, instance=instance, operation="bench", read_write="READ", policy_decision="ALLOW", result_status="SUCCESS")))
    results.append(_measure(
        "federated_search_planning_empty_read_fns",
        lambda: federated_search(identity, registry, "q", read_fns={}),
    ))

    def _real_doc_read():
        req = ConnectorReadRequest(identity=identity, connector_instance_id=instance.connector_instance_id, query="benchmark")
        return search_documents(identity, instance, req)

    results.append(_measure("document_store_read_including_real_docstore_query", _real_doc_read, n=50))
    return results


if __name__ == "__main__":
    for r in run_all():
        print(f"{r.name}: mean={r.mean_ms:.3f}ms p95={r.p95_ms:.3f}ms (n={r.n})")
