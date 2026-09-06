"""
Connector -> Memory Continuum bridge (Phase 9 spec §37-38). Connector
content becomes a `MemoryCandidate` ONLY -- promotion to durable semantic
memory remains `MemoryArbiter`'s own, unchanged, explicit governance
(spec §37: "connector content may become memory candidates only through
normal Memory Continuum governance... do not automatically dump
Slack/Drive/email/database rows into durable semantic memory").

Activates `orca.memory.contracts.MemoryScope.TENANT` -- a value already
DEFINED in Phase 5 as "reserved contract surface for a future multi-
tenant deployment" (see that module's own docstring) -- for real, for the
first time, using the existing `org_id` as `scope_id` (spec §6's "identity
comes from platform/runtime context," reused, not reinvented).
"""
from __future__ import annotations


def connector_result_to_memory_candidate(instance, result, *, tenant_id: str, evidence_id: str | None = None):
    """
    Returns a `orca.memory.contracts.MemoryCandidate` scoped to
    `MemoryScope.TENANT`/`tenant_id` -- retains the connector instance and
    resource scope in `entities` (spec §38: "a memory derived from
    Project A's private repository must not become user-global unless
    policy explicitly permits it" -- the TENANT scope itself is that
    enforcement point; `orca.memory.firewall` already refuses to serve a
    TENANT-scoped record to a DIFFERENT scope_id, unchanged from Phase 5).
    """
    from orca.memory.contracts import MemoryCandidate, MemoryEvidence, MemoryScope

    if not result.normalized_content:
        return None
    claim_text = str(result.normalized_content[0].get("text", result.normalized_content[0]))[:500]
    evidence_refs = [MemoryEvidence(truth_evidence_id=evidence_id)] if evidence_id else []

    return MemoryCandidate(
        extracted_claim=claim_text,
        entities=[f"connector:{instance.connector_instance_id}", f"scope:{instance.scope.resource_path}"],
        evidence_refs=evidence_refs,
        scope=MemoryScope.TENANT,
        scope_id=tenant_id,
    )
