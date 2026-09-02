# Memory Migration State (Phase 5.1, spec §16)

Explicit migration state per store, so operational authority is obvious
rather than implicit. Not a literal enum in code (spec §16: "do not
copy this enum blindly if a simpler architecture already exists") — the
existing classification in
[LEGACY_MEMORY_AUTHORITY_AUDIT.md](LEGACY_MEMORY_AUTHORITY_AUDIT.md)
already carries this information; this document is the migration-state
summary view of that same audit.

| Store | State | Notes |
|---|---|---|
| `orca/memory/*` (Memory Continuum) | **CONTINUUM_PRIMARY** | Authoritative for `CognitiveKernel` memory recall, `WorkingMemory` finalization, Truth Fabric refresh. |
| `orca/brain/memory.py::LongTermMemory` (legacy ChromaDB) | **DUAL_WRITE** | Serves a genuinely different purpose (raw semantic search over conversational turns for the AgentLoop tool-use path) that Memory Continuum doesn't replace — see [LEGACY_MEMORY_AUTHORITY_AUDIT.md](LEGACY_MEMORY_AUTHORITY_AUDIT.md)'s §10 resolution. No migration planned; kept indefinitely as a deliberate second store, not a transitional one. |
| `orca/brain/memory.py::SemanticMemory` (legacy diskcache "facts") | **DUAL_WRITE, migration in progress** | `distill_and_save()` now ALSO promotes through Memory Continuum (`MemoryCandidate`→`MemoryArbiter`) — the legacy per-session key is kept only because `orca/variants/core.py`'s `/recall` command still reads it directly. Retiring the legacy key entirely requires migrating that one CLI read site, not done this phase (small, isolated, low-risk follow-up). |
| `orca/brain/memory.py::SemanticMemory`'s `all_sessions_summary` | **RETIRED** | The unscoped cross-session blob — no code writes to it anymore (Phase 5.1 fix). `delete_session_facts()` still knows how to scrub it for cleanup of any pre-existing data written before this fix, but nothing produces new content there. |
| `orca/brain/memory.py::EpisodicMemory` (legacy, mutable overwrite) | **LEGACY_ONLY** | Still written by `distill_and_save()`/`save_session()`; not migrated to the append-only ledger (that would change `OrcaCore`'s CLI session-save semantics, out of scope for this phase's "memory closure only" mandate). Covered by the deletion cascade. |
| `orca/brain/knowledge_graph.py::KnowledgeGraph` | **LEGACY_ONLY, by design** | Not a migration target — deliberately distinct from `orca/memory/entity.py::EntityMemoryRecord` per spec §57, meant to coexist permanently. |
| `orca/memory/episodic.py` (Memory Continuum episodic ledger) | **CONTINUUM_PRIMARY** | The append-only ledger; the target architecture for new episode writes going forward. |

## Dual-write consistency (spec §11)

For the one dual-write this phase actively manages
(`distill_and_save()`'s legacy `fact:session_{id[:8]}` key + its new
Memory Continuum promotion), consistency is handled the smallest way
that's actually robust for these two stores:

- **Shared identity**: both writes are keyed by the same `session_id` —
  there is no separate "event ID" to reconcile, since both writes derive
  from the exact same `summary` string computed once.
- **Idempotency**: the Memory Continuum side is idempotent by
  `content_hash` on `episodic.append_episode()` (used by
  `turn_ingest.maybe_ingest_turn()`, the same pipeline
  `_finalize_working_memory()` calls) — reprocessing the same summary
  twice does not create a duplicate episode. The legacy diskcache write
  (`store_fact()`) is a plain key overwrite — idempotent by construction
  (writing the same value twice is a no-op in effect).
- **Partial-failure handling**: `distill_and_save()` wraps the Memory
  Continuum promotion in a `try/except: pass` — if it fails, the legacy
  write (which happens first) still succeeds and is returned to the
  caller. This is a deliberate choice, not silent success-claiming: the
  function's return value (`summary`) and its legacy persistence are
  unaffected by the additive promotion's failure, and the failure itself
  produces no user-visible error since promotion is best-effort
  enrichment, not the function's primary contract. No reconciliation job
  exists to detect a promotion that silently failed — a real, disclosed
  gap for a future phase, not a claim of full outbox-pattern durability.
