# Memory Continuum Latency (Phase 5.1, spec §23-26)

## Environment

Local machine, this session's own hardware. Storage: disk-backed
JSON/JSONL (no external database — see [ARCHITECTURE.md](ARCHITECTURE.md)).
`orca/memory/latency_bench.py` — run directly with
`.venv/bin/python -m orca.memory.latency_bench`. p50 (median) reported
over the repetition counts shown; deterministic operations use 20-100
reps (cheap enough to repeat many times), the two live-Ollama operations
use 3 reps each (bounded by real model-call cost) — not enough for a
defensible p95, so only p50 is reported, per spec §23's explicit
instruction not to fabricate p95 from too few samples.

## Deterministic operations (no Ollama, this session's real run)

| Operation | p50 | Reps | Corpus |
|---|---|---|---|
| WorkingMemory creation + 5 entity/recalled-id updates | 0.006 ms | 50 | n/a |
| Memory Firewall `check()` | 0.004 ms | 50 | n/a |
| Semantic recall (`retrieval.recall()`) | 5.56 ms | 20 | 200 records |
| Episodic recall (`episodic.list_episodes()`) | 0.84 ms | 20 | 200 episodes |
| Procedural recall (`find_by_name()`) | 0.037 ms | 50 | 1 record |
| Failure recall (`find_relevant()`) | 0.99 ms | 20 | 50 records |
| Candidate promotion (extract → duplicate check → promote) | 0.39 ms | 20 | n/a |
| `CognitiveKernel.plan()` for a no-memory objective | 0.021 ms | 100 | n/a |

All of these are sub-10ms even at a 200-record corpus — the disk-backed
JSON approach (spec §49's "don't rewrite storage for architectural
purity") holds up fine at this scale; a much larger corpus (thousands+
records per scope) would need revisiting, but no single session's memory
volume is expected to approach that.

## Live-Ollama operations (real run, 3 reps each)

| Operation | p50 |
|---|---|
| Truth Fabric refresh (`refresh_stale_memory()`, real DENSE retrieval via one matching DocStore chunk) | 147–162 ms (two real runs; reported range, not averaged into a false-precision single number) |
| Full Kernel round-trip, no memory recall (`execute()`, FAST tier) | 522–672 ms across two real runs |
| Full Kernel round-trip, memory recall requested but corpus empty (`execute()`, BALANCED tier) | 4,580–4,946 ms across two real runs |

## The honest finding on spec §24's fast-path requirement

The raw difference between the two full-Kernel-round-trip rows above is
**~4 seconds** — but attributing that to "memory subsystem overhead"
would be wrong, and disclosing it as such was the actual mistake almost
made while building this benchmark. Direct trace:

```
no-memory objective:      "What is the capital of France?"
  -> ModelPolicyCharacteristic.FAST
memory-recall objective:  "What did I tell you earlier about my project?"
  -> ModelPolicyCharacteristic.BALANCED
```

The two objectives resolve to **different model tiers** — a pre-existing
`orca/cognitive/policy.py` intent→policy decision, unrelated to Memory
Continuum. The ~4-second gap is overwhelmingly the cost of a heavier
model tier responding, not memory recall + firewall work (which,
measured in isolation above, is single-digit-milliseconds). This is
exactly the misattribution spec §26 warns against for Truth Fabric,
found here in the fast-path benchmark instead, and corrected before
being reported: `bench_fast_path_vs_memory_recall_kernel_roundtrip()`'s
own output carries this caveat inline, not just in this document.

**Spec §24's actual requirement — "a normal conversational request that
does NOT require memory recall must not incur expensive long-term-memory
traversal" — is satisfied**: `IntentPlan.requires_memory` gates the
entire recall path (`orca/cognitive/kernel.py::execute()`'s `any(op.type
== OperationType.RECALL_MEMORY ...)` check), so a no-memory request never
calls `retrieval.recall()`/the Firewall at all — confirmed by the
`kernel_fast_path_no_memory_plan_only` benchmark and by
`tests/test_kernel_memory_recall_integration.py`'s existing coverage.

## Recall latency budget (spec §25)

Memory operations consume `BudgetDimension.MEMORY_OPERATIONS`
(`orca/cognitive/kernel.py::_recall_memory_and_enrich()`) — a budget
exhaustion degrades to the plain objective rather than blocking the
request (already tested:
`tests/test_kernel_memory_recall_integration.py::
test_recall_consumes_memory_operations_budget`). A dedicated wall-clock
timeout on the recall call itself (distinct from the budget-unit cap) is
not implemented in this phase — given the deterministic recall path
measures under 10ms even at a 200-record corpus, a timeout would not
currently trigger in practice; this is disclosed as a gap for a future
phase to close if corpus sizes grow enough to matter, rather than a
timeout mechanism built preemptively for a cost that isn't real yet.
