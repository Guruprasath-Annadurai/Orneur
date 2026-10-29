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
| L02-02b…  | 02 | – | Upload validation, injection tests, citation identity (`retrieve()` omits `doc_id`), multi-document attribution, abstention, cancellation/quota in doc turns | OPEN |
| L02-03 … L02-08 | 03–08 | – | Recovery contract, account verification, reconciliation, operations, customer journeys, model-identity audit | NOT STARTED |

## Measured (L02-02a), fake provider, one question in a document session
| | requests (answering) | note |
|---|---|---|
| baseline `9cb864c` | 3 non-side calls: Kernel non-stream answer (discarded) + RAG stage + streamed answer | `test_l02_document_dispatch.py` fails 2/4 on baseline |
| this branch | RAG stage + streamed answer | 4/4 pass |
Fixture provider only; no latency or capacity claim.
