# Legacy Memory Authority Audit (Phase 5.1, spec §7)

Every production memory-related path, classified. Legend:
`MEMORY_CONTINUUM_AUTHORITATIVE` / `LEGACY_ADAPTER` / `LEGACY_DUAL_WRITE` /
`READ_ONLY_LEGACY` / `MIGRATION_ONLY` / `DEAD` / `UNEXPECTED_MEMORY_BYPASS`.

| Path | Classification | Notes |
|---|---|---|
| `orca/brain/memory.py::MemoryEngine.distill_and_save()` | **LEGACY_DUAL_WRITE (fixed this phase)** | Was: raw `brain.complete()` output stored as an untyped "fact" string in TWO places, one of them (`all_sessions_summary`) globally unscoped across every session. **Fixed** — see [§8 below](#distill_and_save-audit-spec-8). Now ALSO routes the summary through `MemoryCandidate` → `MemoryArbiter`, promoted at `UNVERIFIED` (no evidence). The remaining legacy write (`fact:session_{id[:8]}`) is session-scoped, still read directly by `orca/variants/core.py`'s `/recall` command — an explicit, documented dual-write, not a bypass. |
| `orca/brain/memory.py::MemoryEngine.commit_to_long_term()` (→ `LongTermMemory`) | `LEGACY_DUAL_WRITE` | Unconditional per-turn write to the ChromaDB/keyword vector store, called from `orca/serve/api.py`'s `/api/chat`, `/api/stream`, `/api/ultra`, alongside the new significance-gated `orca/memory/turn_ingest.py::maybe_ingest_turn()` call added in Phase 5. See [§10 below](#commit_to_long_term-dual-write-spec-10) for the resolution. |
| `orca/brain/memory.py::MemoryEngine.recall_context()` (→ `LongTermMemory.recall()`) | `READ_ONLY_LEGACY` | Session-scoped (per-session ChromaDB collection, `f"orca_{session_id[:8]}"`) — no cross-scope read risk by construction, since each session has its own physically separate collection. Still called directly in `orca/serve/api.py` (feeds `enriched` for the AgentLoop-executed path only, per Phase 4.1's `use_kernel_direct` fix — never for a Truth-Fabric- or Kernel-direct-answered turn). |
| `orca/brain/memory.py::MemoryEngine.load_prior_context()` | **UNEXPECTED_MEMORY_BYPASS (fixed this phase) → now READ_ONLY_LEGACY** | Was reading the unscoped `all_sessions_summary` blob — a real, confirmed cross-session leak reachable via `orca/tools/__init__.py::_recall_memory_engine`'s `memory_recall` agent tool fallback (registered for every web session's `AgentLoop`, per `orca/serve/api.py`'s `_Session.__init__`). **Fixed**: now reads only `fact:session_{id[:8]}`, this session's own key. |
| `orca/brain/memory.py::EpisodicMemory` (`save()`/`load()`) | `LEGACY_ADAPTER` | Mutable full-file-overwrite episode log, superseded (not replaced) by `orca/memory/episodic.py`'s append-only ledger for NEW writes going forward — see Phase 5's own [ARCHITECTURE.md](ARCHITECTURE.md). Still called by `distill_and_save()`/`save_session()`, and by `orca/serve/account_delete.py`'s deletion cascade (its file is deleted, correctly). |
| `orca/brain/knowledge_graph.py::KnowledgeGraph` | `LEGACY_ADAPTER` | Session-scoped LLM-extracted entity graph, distinct from `orca/memory/entity.py::EntityMemoryRecord` — the two are meant to coexist (spec §57), not merge. Covered by `account_delete.py`'s cascade. |
| `orca/serve/api.py`'s per-turn `commit_to_long_term()` + `turn_ingest.maybe_ingest_turn()` calls | `LEGACY_DUAL_WRITE` | See [§10](#commit_to_long_term-dual-write-spec-10). |
| `orca/memory/*` (all Phase 5 modules) | `MEMORY_CONTINUUM_AUTHORITATIVE` | The new system. Authoritative for: `CognitiveKernel`'s direct-answer memory recall (Phase 5's Finding #2 fix), the deletion cascade extension, Truth Fabric refresh. |
| `orca/serve/account_delete.py` | `MEMORY_CONTINUUM_AUTHORITATIVE` for its own orchestration | Calls into every store above (legacy and Continuum) — the one place that is deliberately "authoritative over everything," by design (a deletion cascade's whole job is touching every store). |
| `orca/serve/session_store.py` (Redis) | `READ_ONLY_LEGACY` / not a memory-fact store | Only ever holds `AgentLoop` history + `model_variant` — never touched by `MemoryArbiter`/Memory Continuum, and was never in scope to be (it's transport/continuity state, not semantic memory). |
| `orca/tools/__init__.py::_recall_memory_engine` (the `memory_recall` agent tool) | `READ_ONLY_LEGACY` (fixed indirectly) | Calls `engine.long.recall()` then falls back to `engine.load_prior_context()` — inherits the `load_prior_context()` fix above. No code change needed in this file itself. |
| `orca/variants/core.py`'s `/remember` CLI command | **UNEXPECTED_MEMORY_BYPASS (fixed this phase)** | Was writing directly into the same unscoped `all_sessions_summary` blob with zero `MemoryArbiter` involvement. **Fixed**: now routes through `MemoryCandidate`/`MemoryArbiter`, scoped to the session, carrying an explicit `human_explicit_remember` evidence note (spec §15's human-authoritative-for-this-session distinction — never claimed as external factual evidence). |
| `orca/variants/core.py`'s other direct `self.memory.commit_to_long_term()`/`self.memory.recall_context()` calls | `LEGACY_ADAPTER` | Same class as the web API's own per-turn legacy calls — the CLI variant (`OrcaCore`) predates Memory Continuum and was not migrated to call `turn_ingest.maybe_ingest_turn()` in this phase (out of scope — see [MEMORY_MIGRATION.md](MEMORY_MIGRATION.md)'s migration-state table). |

## `distill_and_save()` audit (spec §8)

Traced directly from source (`orca/brain/memory.py`, pre-fix version),
answering spec §8's exact questions:

- **Accepts**: a `brain` object exposing `.complete(messages, system,
  temperature, max_tokens)` — the raw `OrcaBrain`/`GatewayBrain`
  interface, not `ModelGateway` directly (a `ModelGateway` bypass class,
  same as Phase 4's Deep RAG disclosure — not fixed in this phase, since
  fixing the Gateway-routing gap is separate from fixing the
  authority/scope gap this phase targets).
- **Generates**: one LLM completion — a free-text bulleted "key facts"
  summary. No structured claim extraction, no `MemoryCandidate`.
- **Stored** (before this fix): `fact:session_{id[:8]}` (session-scoped)
  **and** `fact:all_sessions_summary` (a single GLOBAL string merging
  every session's summary, capped at the last 4000 characters). Also
  called `save_session()` → `EpisodicMemory.save()` (legacy, full-file
  overwrite).
- **Trusts**: the raw LLM output completely. No verification, no
  duplicate/contradiction check, no `MemoryArbiter` involvement.
- **Indexes**: not vector-indexed by this function itself; but
  `load_prior_context()` reads the merged string back and it gets
  injected as `[Prior context]` into a brand-new session's initial
  history (`orca/serve/api.py::_Session.__init__`).
- **Marks as fact**: yes — stored under `SemanticMemory`, the class
  whose entire purpose is "distilled facts." No epistemic-state concept
  existed on this path at all (it predates Phase 5's `EpistemicState`
  enum — it's an untyped string, not a `SemanticMemoryRecord`).
- **Scopes**: `fact:session_{id[:8]}` is session-scoped by convention.
  `fact:all_sessions_summary` was **explicitly unscoped** — the exact
  bug this phase fixes.
- **Deletes**: only reachable via Phase 5's `SemanticMemory.
  delete_session_facts()` (added in the base Phase 5 work) — cleanup,
  not prevention.

**Answering spec §8's central question directly: yes, confirmed by code
trace — model-generated, unverified content COULD become durable
"factual" memory with zero `MemoryArbiter`/evidence-lineage/Firewall
governance, AND that memory was readable across session boundaries with
no scope check, via a live, reachable path (the `memory_recall` agent
tool available on every multi-tenant web session).** This was not a
theoretical risk — it was demonstrated live in
`tests/test_memory_legacy_authority.py` (reproducing the leak against
the pre-fix code, then proving the fix closes it).

## `commit_to_long_term()` dual-write (spec §10)

| Destination | Purpose | Canonical owner | Readers | Deletion semantics | Scope semantics | Migration need |
|---|---|---|---|---|---|---|
| `LongTermMemory` (ChromaDB/keyword, per-session collection) | Fast semantic-similarity search over this session's own raw turn history, for the AgentLoop-executed conversational path | Legacy (`orca/brain/memory.py`) | `recall_context()` (AgentLoop path only — never the Kernel-direct or Truth-Fabric-answered paths, per Phase 4.1's `use_kernel_direct` split), `_recall_memory_engine` tool | `account_delete.py` deletes the whole per-session ChromaDB collection via `DocStore`-style cleanup (session-scoped file/collection removal) | Session-scoped (separate collection per session — no cross-scope read is even possible by construction) | None — stays as-is |
| `orca/memory/episodic.py` + `MemoryArbiter` (Memory Continuum) | Significance-gated, evidence-lineage-backed durable memory, feeding `CognitiveKernel`'s real memory recall | Memory Continuum (`orca/memory/`) | `orca/cognitive/kernel.py::_recall_memory_and_enrich()` | `orca/memory/deletion.py::delete_scope()` | Session-scoped (today); contract supports the full scope enum for future expansion | N/A — this IS the target architecture |

**Decision (spec §10's required choice): Option A — Memory Continuum
authoritative + legacy compatibility write, kept explicit.** The legacy
`LongTermMemory` write is NOT retired, because:
1. It serves a genuinely different purpose (raw semantic-similarity
   search over conversational history for the AgentLoop tool-use path)
   that Memory Continuum's significance-gated, structured-claim model
   does not replace — a tool-use agent benefits from "what did we
   discuss 10 turns ago" recall even for content too trivial to become
   a durable semantic fact.
2. It is scope-safe by construction (physically separate collections
   per session) — unlike the `all_sessions_summary` bug, this dual-write
   was never the source of the cross-scope leak this phase closes.

This is documented explicitly (not left as silent, uncontrolled dual
authority) in [MEMORY_MIGRATION.md](MEMORY_MIGRATION.md), including the
idempotency/consistency treatment required by spec §11.
