# Memory Evidence Ledger (Phase 5)

The signature Orneur mechanism (spec §11): every semantic factual memory
must be able to answer **"WHY DOES ORNEUR BELIEVE THIS?"** by walking a
real, structural list — never inventing provenance retrospectively.

## The mechanism

`SemanticMemoryRecord.source_refs` (episode ids) +
`SemanticMemoryRecord.evidence_refs` (`MemoryEvidence` list) together
form the lineage. `MemoryArbiter.promote()` (`orca/memory/arbiter.py`)
copies both directly from the `MemoryCandidate` that was promoted — it
never fabricates a `source_refs`/`evidence_refs` entry that the
candidate didn't actually carry.

```
SemanticMemoryRecord: "Project X uses PostgreSQL."
  source_refs: ["mem-ep-a1b2c3"]              -- the episode this was extracted from
  evidence_refs:
    - episode_id: "mem-ep-a1b2c3"
      note: "user stated this directly in chat"
    - document_ref: "deployment_config.yaml"
      note: "confirmed in repository config"
```

## Honest epistemic state (spec §14)

`MemoryArbiter.promote()` sets `epistemic_state=SUPPORTED` only when
`evidence_refs` is non-empty; a candidate with no evidence at all
promotes at `UNVERIFIED`, never `KNOWN`/`SUPPORTED` — the exact fix for
`orca/brain/memory.py::distill_and_save()`'s current behavior (a raw
model summary stored as fact with no verification step at all, see
[CURRENT_MEMORY_ARCHITECTURE.md](CURRENT_MEMORY_ARCHITECTURE.md)'s
Finding #3).

## Truth Fabric lineage (spec §12)

When a factual candidate originates from Truth Fabric (web retrieval,
documents, RAG, research), its `MemoryEvidence` carries
`truth_request_id`/`truth_evidence_id`/`truth_claim_id`/
`citation_verdict_state` — copied directly from the already-computed
`TruthResult`, never re-derived by a second, unrelated verifier (spec
§12's explicit instruction). `orca/memory/refresh.py::refresh_stale_memory()`
demonstrates this: it calls `TruthFabric.assess_evidence()` once, and the
resulting `Evidence.evidence_id`s populate the new record's
`evidence_refs` directly.

## Truth-Fabric-relationship preservation in contradiction resolution

When a `MemoryCandidate`'s evidence already carries a Truth Fabric
contradiction relationship (convention:
`MemoryEvidence.note == "truth_relationship:<VALUE>"`, written by
whatever caller already ran
`orca.truth.contradiction.detect_evidence_contradictions()`),
`MemoryArbiter.resolve_contradiction()` maps it directly onto Memory's
own `ContradictionResolution` vocabulary
(`DIRECT_CONTRADICTION→CONTESTED`, `TEMPORALLY_RECONCILABLE→
TEMPORAL_CHANGE`, `SCOPE_DIFFERENCE→SCOPE_DIFFERENCE`,
`LIKELY_CONFLICT→CONTESTED`) rather than re-running its own heuristic —
proven by
`tests/test_memory_contracts_arbiter.py::test_truth_fabric_relationship_is_preserved_not_rederived`.

## Never evidence by default (spec §43)

A `MemoryEvidence` pointing at an episode (a user's own statement, an
unverified observation) is provenance, not proof. For STRICT/AUDIT_GRADE
requests, Truth Fabric — not the memory's own `evidence_refs` list —
decides whether the referenced evidence remains sufficient/current. No
code in this phase ever presents "Orneur remembers this" as external
verification.
