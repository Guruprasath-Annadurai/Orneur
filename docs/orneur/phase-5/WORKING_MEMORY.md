# Working Memory (Phase 5.1)

Phase 5 introduced the `WorkingMemory` contract but never threaded a
literal instance through `CognitiveContext`. This phase closes that gap
(spec §3-6).

## A real runtime object, per request

`CognitiveKernel.execute()` creates one `orca.memory.contracts.
WorkingMemory` instance at the start of every request
(`working_memory = WorkingMemory(objective=request.objective)`,
`lifecycle_state=ACTIVE`). `orca.cognitive.contracts.CognitiveContext`
gained a `working_memory` field to carry it (typed loosely as `Any` to
avoid a circular import — `orca.memory.contracts` already imports
`PrivacyClass` from `orca.cognitive.contracts`).

## Bounds (spec §4)

Every list field has its own cap and deterministic FIFO eviction — the
oldest entry is dropped to make room for a new one, never silently
grown or refused outright, via `WorkingMemory.add_*()`:

| Field | Cap | Method |
|---|---|---|
| `entities` | 30 | `add_entity()` |
| `recalled_memory_ids` | 10 | `add_recalled_memory_id()` |
| `tool_observations` | 20 | `add_tool_observation()` |
| `decisions`/`unresolved_questions`/`next_actions`/`hypotheses` | 20 each | `add_decision()` etc. |

A single item larger than `MAX_WORKING_MEMORY_SERIALIZED_CHARS` (8000,
a character-count proxy for a token budget — a real tokenizer call would
make WorkingMemory itself expensive to update, defeating its purpose as
cheap per-request scratch state) is rejected outright, and
`serialized_size()` is re-checked after every append, evicting from the
front of the just-modified list until the whole object is back under
the cap. Proven in `tests/test_kernel_working_memory.py`.

## Populated by, and only by, governed sources

Today, exactly one subsystem populates `WorkingMemory`:
`CognitiveKernel._recall_memory_and_enrich()` calls
`working_memory.add_recalled_memory_id(m.memory_id)` for every memory
that survived the **Memory Firewall** — never a raw retrieval hit. This
is the direct security property spec §6 requires: a `DISPROVEN`,
cross-scope, or privacy-insufficient memory can never end up referenced
in `WorkingMemory`, because it never reaches the `allowed` list the
population loop iterates over in the first place. Verified directly by
`tests/test_kernel_working_memory.py::
test_working_memory_never_imports_a_firewall_rejected_memory` and
`test_working_memory_never_imports_cross_session_memory`.

## Lifecycle (spec §5)

`WorkingMemoryLifecycle`: `CREATED` → `ACTIVE` → `COMPLETED` /
`DISCARDED`. `CognitiveKernel._finalize_working_memory()` is the sole
authority on the terminal state, called once at the direct-answer
completion point:

```
no session_id                          -> DISCARDED
significance filter says "not worth it" -> DISCARDED
significant turn                        -> COMPLETED (episode + candidates emitted)
```

It reuses `orca.memory.turn_ingest.maybe_ingest_turn()` — the exact same
significance→candidate→promotion pipeline an AgentLoop-executed turn
already gets (see [ARCHITECTURE.md](ARCHITECTURE.md)), so a
Kernel-answered turn and an AgentLoop-answered turn are governed
identically, not by two divergent policies. **WorkingMemory itself is
never persisted wholesale** — only the derived episode/candidates are,
and only when the significance filter says so.

## Trace linkage (spec §32)

`CognitiveTraceBuilder.record_working_memory_disposition()` is additive
— it sets `memory_query_id` only if a prior recall hasn't already set it,
and appends to `memory_promotion_decisions` — so a request that both
recalled memory AND finalized WorkingMemory ends up with one coherent
trace linking the `MemoryQuery`, the recalled ids, and the final
lifecycle disposition, rather than the second call silently overwriting
the first's fields (a real bug caught and fixed while building this:
the naive approach of calling the existing `record_memory_trace()`
twice would have wiped the recall-specific fields).

## What this phase did NOT build

A `WorkingMemory` populated by tool observations from a running
AgentLoop tool-use session — today's Kernel direct-answer path is the
only one that creates and threads a `WorkingMemory` instance;
`USE_TOOL`/`DELEGATE_AGENT` plans still defer entirely to the existing
serving stack (per Phase 3's `CUTOVER.md`) and don't yet get their own
`WorkingMemory`. A future phase can extend the same object without
changing its contract.
