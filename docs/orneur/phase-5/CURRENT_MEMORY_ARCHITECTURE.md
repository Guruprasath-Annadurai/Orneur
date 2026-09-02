# Current Memory Architecture Audit (Phase 5, required first action)

Maps exactly what exists today, before any Memory Continuum code is
written. Classification legend: REAL / PARTIAL / LEGACY / DUPLICATED /
UNSAFE / UNVERIFIED / MISSING.

## The existing four-layer engine (`orca/brain/memory.py`)

| Component | Classification | Notes |
|---|---|---|
| `ShortTermMemory` | REAL | Sliding-window in-process message list (`max_turns=20`), no persistence. This is Phase 5's `WorkingMemory` starting point (§7, §58). |
| `LongTermMemory` | REAL, but UNSCOPED SIGNIFICANCE (see finding #1 below) | ChromaDB per-session collection, JSONL keyword fallback if ChromaDB unavailable. Stores raw `Q:/A:` text blobs, not typed facts. |
| `EpisodicMemory` | PARTIAL | One JSON file per session, **overwritten in full on every `save()`** (`open(path, "w")` — not append-only). This is the opposite of Phase 5's Episodic Ledger requirement (§8: immutable/append-only); today a session's episode file is mutable and gets replaced wholesale each time `save_session()` runs. |
| `SemanticMemory` | PARTIAL | A single `diskcache` key-value store (`store_fact`/`store_concept`). No entity linkage, no evidence lineage, no temporal validity, no epistemic state — a flat fact/string cache, not a structured belief system. |
| `MemoryEngine.distill_and_save` | REAL, UNVERIFIED PROMOTION | Summarizes a session via a **raw `brain.complete()` call** (not routed through `ModelGateway`/Truth Fabric) and stores the model's own summary text directly as semantic fact — "LLM said it, therefore store it" (exactly what Phase 5 spec §10 says not to do). No candidate/promotion step exists today. |
| `orca/brain/knowledge_graph.py::KnowledgeGraph` | REAL (self-documented v1 limits) | Per-session LLM-extracted entity/relationship triples. Its own docstring already discloses: no cross-session entity resolution, no temporal fact versioning, no contradiction detection. Maps cleanly to Phase 5's `EntityMemory` (§19, §57) — this is the "Entity Graph" the spec says to integrate through contracts, not merge with the new Evidence Graph or Memory Continuum. |

## Finding #1 — no significance filter (spec §9)

Every single chat turn, unconditionally, becomes durable `LongTermMemory`
(`orca/serve/api.py` lines 830, 1103, 1613: `sess.memory.commit_to_long_term(f"Q: ...\nA: ...")`
runs after every `/api/chat`, `/api/stream`, and `/api/ultra` turn, with
no significance check at all). There is no distinction between "user
asked to remember this" and "user said hello." This is the single
highest-priority gap Phase 5's `MemoryCandidate` pipeline (§10) and
significance filter (§9) exist to close.

## Finding #2 — RECALL_MEMORY is marked SUPPORTED_NOW but never actually consulted by the Kernel's direct-answer path

`orca/cognitive/planner.py` marks `OperationType.RECALL_MEMORY` as
`SUPPORTED_NOW` ("existing MemoryEngine"). But `orca/cognitive/kernel.py`
buckets `RECALL_MEMORY` into `_KERNEL_EXECUTABLE_OPS` alongside
`ANSWER_DIRECTLY`/`REASON`, and `_answer_directly()` calls `ModelGateway`
with **only `request.objective`** — no memory recall happens inside the
Kernel at all. The actual `sess.memory.recall_context(...)` call in
`orca/serve/api.py` happens in a *separate*, non-Kernel code path, and
only its result feeds `enriched` — which the Kernel's own direct-answer
branch (`final = cognitive_result.output`) **never uses**, since that
branch bypasses `enriched` entirely (see `orca/serve/api.py`'s
`use_kernel_direct` branching, same code Phase 4.1 already touched).
Net effect: when the Kernel answers directly, whatever memory context was
recalled is silently discarded. This matches the exact "confusing dead
judge that appears active but isn't" pattern Phase 4's spec (§22) warned
about — here applied to memory recall instead of a hallucination judge.
Phase 5's Kernel integration (§41-42) fixes this by making the
Kernel itself own the recall step through a real `WorkingMemory`/
`MemoryRecallResult` contract wired into `CognitiveContext` before
`_answer_directly` runs.

## Finding #3 — `distill_and_save` bypasses `ModelGateway`

`orca/brain/memory.py::MemoryEngine.distill_and_save()` calls
`brain.complete(...)` directly — the same class of bypass Phase 4
disclosed for the Deep RAG pipeline's raw-urllib Ollama calls
(`docs/orneur/phase-4/CURRENT_TRUTH_PIPELINE.md`), now found in memory
distillation. Not fixed in Phase 4/4.1 (out of that phase's scope); in
scope for Phase 5 since the new `MemoryCandidate` extraction pipeline
(§10) replaces this call site anyway.

## Deletion / privacy (`orca/serve/account_delete.py`, `orca/serve/session_store.py`)

| Component | Classification | Notes |
|---|---|---|
| `delete_account()` cross-store cascade | REAL, genuinely good | Deletes `EpisodicMemory` file, `DocStore` vectors + registry, `KnowledgeGraph` entities/relationships, Redis session state, session title — best-effort per-store, never lets one store's failure block the rest. Explicitly documents what it does NOT delete (audit log entries — tamper-evident by design; anonymous pre-login sessions — never tracked). **Phase 5 must extend this list**, not replace it, to cover new stores: `SemanticMemory`/episodic ledger records, procedural/failure memory, and the new evidence-lineage index — see §38-39. |
| `orca/auth/store.py::get_user_session_ids` | REAL | The only reason cross-session deletion is possible at all — populated by `_get_session()` for authenticated requests. |
| `SemanticMemory` (the diskcache one) | **MISSING from deletion cascade** | `account_delete.py` never touches `orca/brain/memory.py::SemanticMemory`'s diskcache store — a real, pre-existing gap: distilled "facts" from a deleted user's sessions currently persist in the global semantic diskcache forever, keyed by session-id-derived strings, unreachable by the deletion cascade. **Must be fixed in Phase 5**, since the new Memory Continuum inherits this cache's role. |
| `session_store.py` (Redis) | REAL | Opt-in via `ORNEUR_REDIS_URL`; only used for `AgentLoop` history + `model_variant`, not for any of the memory layers above. No-op when disabled, never raises when Redis is unreachable. |

## Privacy classification convention already defined

`orca.cognitive.contracts.PrivacyClass` (`STANDARD`/`SENSITIVE`/`RESTRICTED`)
already exists and is used for request-content classification. Phase 5
reuses this exact enum for memory sensitivity (spec §37: "use current
project conventions if already defined") rather than inventing a
parallel `PUBLIC`/`INTERNAL`/`PRIVATE`/`SENSITIVE` scheme.

## What does NOT exist today (MISSING, confirmed by search)

- Any `MemoryCandidate`/promotion pipeline — MISSING.
- Any `MemoryArbiter`, contradiction/temporal reconciliation for
  memory — MISSING (the Truth Fabric one, `orca/truth/contradiction.py`,
  operates on claims/evidence, not on stored memories).
- Any `ProceduralMemory`/`FailureMemory` — MISSING, net-new (spec §59).
- Any evidence-lineage linkage from a semantic fact back to its source
  episodes/documents — MISSING.
- Any `MemoryFirewall` / scoped recall boundary before content reaches
  `CognitiveContext` — MISSING (memory text is injected as a raw string
  into `enriched`, with no injection/sensitivity/staleness check).
- Any explicit memory scope enum (`GLOBAL`/`TENANT`/`WORKSPACE`/...) —
  MISSING; today's only scoping mechanism is `session_id`
  string-keying, with `user_id`-level scoping existing only indirectly
  via `auth/store.py`'s `user_sessions` table (used for deletion, not
  for recall-time isolation).
- Any memory-specific `CognitiveBudget` dimension or trace metadata —
  MISSING (`orca/cognitive/contracts.py`'s `BudgetDimension` has no
  memory-related entries yet).

## What Phase 5 must NOT rewrite (spec §58)

`ShortTermMemory` (→ `WorkingMemory` foundation) and
`KnowledgeGraph` (→ `EntityMemory` integration point) are functioning,
tested-by-use code with no demonstrated incompatibility with the new
architecture — they are adapted behind new typed interfaces, not
replaced. `EpisodicMemory`'s mutable-overwrite behavior, by contrast,
is directly incompatible with the Episodic Ledger's append-only
requirement (§8) and is superseded by a new ledger, with the old file
format left untouched for any code that still reads it directly.
