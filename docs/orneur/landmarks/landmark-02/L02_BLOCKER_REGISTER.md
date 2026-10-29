# LANDMARK-02 — gap / blocker register (live)

Status of the milestone: **PARTIAL — work in progress.** Nothing below is independently qualified. Baseline `9cb864c99ad323d11626063498a7d1cef0d7d4b5` (PR #136, unmodified).

| ID | Wave | Sev | Finding | State |
|---|---|---|---|---|
| L02-01a | 01 | P1 | Partial deletion reported as success; ownership released; no retry | FIXED (engineering tests), CI pending |
| L02-01b | 01 | P1 | Document delete left keyword-fallback text retrievable; swallowed collection errors | FIXED (engineering tests), CI pending |
| L02-01c | 01 | P1 | No tombstone: stale worker could write derived state after deletion | FIXED (commit/authority/derived writes gated) |
| L02-01d | 01 | P2 | Retention purge / account deletion ignored store failures | FIXED |
| L02-01e | 01 | P2 | Temporary-chat closure does not write the deletion tombstone (own state machine; ignores non-transcript store errors) | OPEN (G-02) |
| L02-01f | 01 | P2 | No live Redis-down / live Ollama-embedding deletion journey yet | OPEN |
| L02-02a | 02 | P1 | Document session generated a discarded Kernel answer (extra dispatch) and charged a quota unit for output the user never saw | FIXED: `defer_direct_answer` (measured below) |
| L02-02b | 02 | P1 | Upload parsed before ownership check; unbounded read; hostile display names; content not validated; no limits | FIXED (engineering tests) |
| L02-02c | 02 | P1 | Chunk identity `(filename, idx)` dropped same-name documents in fusion; sources lost `doc_id` | FIXED |
| L02-02d | 02 | P1 | Unregistered/orphaned chunks retrievable; sufficiency judge fail-open; unrelated question answered as if documents supported it | FIXED (floor + judge honesty + explicit notice) |
| L02-02e | 02 | P2 | Rerank and sufficiency prompts interpolate raw passage text (steering of scores/verdict) | OPEN |
| L02-02f | 02 | P2 | Prompt injection mitigated structurally only; model obedience not provable; emitted tool calls still executed | OPEN (documented) |
| L02-02g | 02 | P3 | No background sweep for a half-deleted single document | OPEN |
| L02-03 … L02-08 | 03–08 | – | Recovery contract, account verification, reconciliation, operations, customer journeys, model-identity audit | NOT STARTED |

## Measured (L02-02a), fake provider, one question in a document session
| | requests (answering) | note |
|---|---|---|
| baseline `9cb864c` | 3 non-side calls: Kernel non-stream answer (discarded) + RAG stage + streamed answer | `test_l02_document_dispatch.py` fails 2/4 on baseline |
| this branch | RAG stage + streamed answer | 4/4 pass |
Fixture provider only; no latency or capacity claim.
