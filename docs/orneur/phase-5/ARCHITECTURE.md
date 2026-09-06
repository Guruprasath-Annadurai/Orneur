# Memory Continuum — Architecture (Phase 5)

## Why not "conversation → summary → embedding → vector database"

That pipeline destroys provenance: once a fact is compressed into a
vector-store row, there is no way back to *why* it was believed. Memory
Continuum's central principle — **memory must retain why it is
believed** — is enforced structurally: every `SemanticMemoryRecord`
carries `source_refs` (episode ids) and `evidence_refs`
(`MemoryEvidence`, pointing at either a Memory Continuum episode or a
Truth Fabric `TruthResult`/`Evidence`/`AtomicClaim`). Compression
(consolidation) never deletes the episodes it was built from.

## The nine memory types (spec §1)

| Type | Module | Persisted? |
|---|---|---|
| Working | `orca/memory/contracts.py::WorkingMemory` | No — ephemeral, per-request, bounded lists |
| Episodic | `orca/memory/episodic.py` | Yes — append-only JSONL ledger |
| Semantic | `orca/memory/store.py` + `arbiter.py` | Yes — mutable JSON-per-record |
| Entity | `orca/memory/entity.py` | Yes — links out to other records by id |
| Procedural | `orca/memory/procedural.py` | Yes |
| Failure | `orca/memory/failure.py` | Yes |
| Evidence | `MemoryEvidence` (a field, not a store) | Embedded in every record above |
| Agent | `orca/memory/agent_memory.py` (`MemoryScope.AGENT`) | Yes — isolated per agent_id |
| Temporal | `valid_from`/`valid_to`/`supersedes` fields on `SemanticMemoryRecord` | A property of semantic memory, not a separate store — see [TEMPORAL_MEMORY.md](TEMPORAL_MEMORY.md) for why this was a deliberate design choice, not an omission |

## Data flow

```
interaction (chat turn)
  → significance filter (orca/memory/significance.py) -- fast, deterministic, no Gateway call
      → insignificant: stops here, nothing durable is written to the ledger
      → significant: MemoryEpisode appended (orca/memory/episodic.py)
          → candidate extraction (orca/memory/candidates.py)
              → MemoryArbiter.decide_promotion() (orca/memory/arbiter.py)
                  → duplicate check, contradiction check, promotion decision
                  → PROMOTED: SemanticMemoryRecord persisted (orca/memory/store.py)

recall (CognitiveKernel, when IntentPlan needs RECALL_MEMORY)
  → MemoryQuery (orca/memory/contracts.py)
      → retrieval.recall() -- scope/entity/epistemic-state/evidence-quality filter, salience ranking
          → Memory Firewall (orca/memory/firewall.py) -- scope, privacy, DISPROVEN, staleness, injection checks
              → enriched objective → ModelGateway
```

## Integration boundaries — what this phase deliberately did NOT merge

- **Entity Graph vs Evidence Graph vs Memory Continuum** (spec §57):
  `orca/brain/knowledge_graph.py::KnowledgeGraph` (LLM-extracted
  subject-predicate-object triples for in-conversation reasoning),
  `orca/truth/graph.py::EvidenceGraph` (provenance/support/contradiction
  edges between Truth Fabric evidence/claims), and
  `orca/memory/entity.py::EntityMemoryRecord` (links memory records to a
  named entity) are three distinct, purpose-built structures. They share
  IDs by reference where relevant (a `MemoryEvidence.truth_evidence_id`
  points into the Evidence Graph's own node ids) — never merged into one
  god-object.
- **Truth Fabric vs Memory** (spec §43): memory is not evidence by
  default. A remembered claim may *point at* Truth Fabric evidence via
  `MemoryEvidence`, but "Orneur remembers this" is never itself cited as
  proof — for STRICT/AUDIT_GRADE requests, Truth Fabric independently
  decides whether the referenced evidence remains sufficient/current
  (see [MEMORY_EVIDENCE_LEDGER.md](MEMORY_EVIDENCE_LEDGER.md)).
- **Existing four-layer engine** (`orca/brain/memory.py`, spec §58):
  `ShortTermMemory` and `KnowledgeGraph` are adapted-behind-new-interfaces
  starting points, not replaced. `EpisodicMemory`'s mutable-overwrite
  behavior is directly incompatible with the append-only Episodic Ledger
  requirement and is superseded by the new ledger for new writes — the
  old file format is untouched for whatever still reads it. See
  [CURRENT_MEMORY_ARCHITECTURE.md](CURRENT_MEMORY_ARCHITECTURE.md) for
  the full audit this decision is based on.

## Storage

No new database dependency (spec §49). Episodic records: one JSONL file
per (scope, scope_id), append-only. Semantic/entity/procedural/failure
records: one JSON file per record, under a scope-hashed directory —
makes per-scope cascade deletion a single directory removal. Both
choices match the project's existing disk-backed-JSON convention
(`DocStore`'s keyword fallback, `KnowledgeGraph`) rather than
introducing a new storage backend for architectural purity alone.

## Kernel integration (spec §41-42)

`CognitiveKernel`'s existing direct-answer path (`ANSWER_DIRECTLY`/
`REASON`/`RECALL_MEMORY`, unchanged bucket from Phase 3) now actually
performs memory recall when `RECALL_MEMORY` is in the plan and a
`session_id` is present — see
[CURRENT_MEMORY_ARCHITECTURE.md](CURRENT_MEMORY_ARCHITECTURE.md)'s
Finding #2 for what this fixes. `IntentPlan` decides when recall runs;
a plan with no `RECALL_MEMORY` operation pays nothing extra (spec §48).
