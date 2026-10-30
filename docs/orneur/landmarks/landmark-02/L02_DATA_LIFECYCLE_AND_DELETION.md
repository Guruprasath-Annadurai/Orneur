# L02-01 — User-data lifecycle and deletion (VERIFIED_ENGINEERING; not independently qualified)

Evidence state: **IMPLEMENTED, engineering tests passing locally; exact-head CI pending; not independently qualified.**
Baseline: `9cb864c99ad323d11626063498a7d1cef0d7d4b5` (PR #136). Code: `orca/serve/deletions.py`, `orca/serve/conversations.py`, `orca/serve/api.py`, `orca/docs/store.py`, `orca/serve/retention.py`, `orca/serve/account_delete.py`.

## 1. Inventory (real implementations only)
| Store | Real? | Cleared by the cascade | Notes |
|---|---|---|---|
| SQLite `conversation_turns`, `session_authority`, `session_export_state` | yes | `conversations.delete` | `secure_delete=ON`, WAL truncated |
| JSONL transcript export | yes (derived) | `conversations.delete` | rebuilt from SQLite, never authoritative |
| Redis session cache / lease | yes (advisory) | `session_store.delete_session` | outage = reported `failed`, retried |
| Working/episodic memory file | yes | `EpisodicMemory.path.unlink` | |
| Long-term vector memory (Chroma) | yes | `LongTermMemory.delete_session` | reports `RECLAIMED` / `DEFERRED` physical reclamation |
| Semantic facts (diskcache) | yes | `SemanticMemory.delete_session_facts` | |
| Memory Continuum (episodic ledger + typed records) | yes | `memory.deletion.delete_scope` | |
| Document chunks: vector collection **and** keyword fallback file | yes | `DocStore.delete_doc_detailed` | **both** are retrieval paths; see §3 |
| Document registry | yes | `unregister_doc` | only after every store confirmed |
| Knowledge graph | yes | `KnowledgeGraph.clear` | |
| Message versions / titles | yes | `message_versions.delete_session`, `_remove_session_title` | |
| Audit log | yes | **not deleted** (tamper-evident by design; stores ids only, never content) | |
| Application backups, search caches, uploaded-file originals | **none exist** | n/a | uploads are chunked into the doc stores; no original is kept (to be re-verified in L02-02) |
| Host backups, disk snapshots, provider-side copies | outside the application | **not covered** | stated in every deletion response (`retention`) |

## 2. Defects reproduced on the baseline (evidence: `evidence/`)
1. **Partial failure reported as success** (`l02_01_baseline_defect_9cb864c.txt`): a failed vector-store delete → `200 {deleted:true}`; the `*_error` key was filtered out of the response; the ownership claim was released, so the owner's retry returned 404 and the leftover store was unreachable.
2. **Document deletion left text retrievable** (`l02_01_doc_delete_baseline_defect_9cb864c.txt`, PR #112's finding, still present): `delete_doc` returned `True` after the collection delete although the keyword-fallback copy of the text remained (`retrieve()` falls back to it whenever the collection errors); and when the collection delete *raised*, the error was swallowed and `True` returned while the chunks stayed in the collection.
3. **No tombstone**: nothing stopped a stale worker or an in-flight generation from writing derived state (memory, Redis, graph) for a conversation that had just been deleted.
4. **Retention purge and account deletion ignored store failures** and released ownership regardless.

## 3. Implemented
* **Durable deletion identity** (`session_deletions` in the authoritative turns database, same file as `commit_turn`'s transaction). Written *first*, idempotently (`ON CONFLICT DO NOTHING`), never removed.
* **Access revoked from that instant**: `_check_session_ownership`, `_get_session`, the session list and search, `commit_turn` (inside its transaction → `session_deleted`), `acquire_authority`, and the derived-write gates (`_omit_long_term`, `_stream_may_publish`, Redis persist, knowledge-graph task). Fails **closed** if the tombstone cannot be read.
* **States**: `revoked → running → complete | partial`; a lease (60 s) lets exactly one worker run the cascade and lets a sweep recover from a crashed holder; `MAX_ATTEMPTS = 8`.
* **Honest result**: `200 {deleted:true,state:"complete"}` only when every store confirmed; otherwise `202 {deleted:false,state:"partial",access_revoked:true,retryable:true,stores:{…ok|failed}}`. No paths, exception text or class names are returned. The owner's ownership claim is kept until completion, so the same `DELETE` resumes the job. A finished deletion is indistinguishable from a conversation that never existed (404).
* **Resume**: `deletions.resume_pending()` runs in the periodic loop (and is callable after a restart); idempotent.
* **Callers unified**: owner `DELETE`, retention purge, account deletion all use the same workflow. (Temporary-chat closure keeps its own state machine — see register G-02.)
* **Documents**: `DocStore.delete_doc_detailed` attempts the collection *and* the keyword file independently, rewrites the fallback via temp file + `os.replace`, preserves unparseable lines, and reports `ok|failed|absent` per store; `DELETE /api/docs/{id}` answers `202` and keeps the document registered when a store failed.
* **Frontend** (no visual change): a `202` shows the existing note "hidden … some stored data could not be removed yet. ORNEUR will keep retrying."

## 4. Deletion correctness matrix (executed)
| Requirement / adversarial case | Test (`tests/test_l02_deletion_lifecycle.py` unless noted) | Result |
|---|---|---|
| Authenticated + ownership-checked; another user's material | `test_cannot_delete_or_resume_another_users_conversation` (no tombstone created by a refused delete; 404/401) | pass |
| Durable identity, concurrent repeats | `test_concurrent_repeated_deletion_is_one_deletion` (6 threads → one `deletion_id`) | pass |
| Delete during generation / stale worker resurrection | `test_stale_worker_cannot_commit_or_regain_authority_after_deletion`, `test_deleted_conversation_cannot_be_streamed_into_or_recreated` | pass |
| Vector store failure; partial honesty; retry | `test_partial_failure_is_not_reported_as_deleted_and_stays_retryable` | pass |
| Interrupted deletion / worker crash / restart | `test_crash_between_tombstone_and_cascade_is_recovered`, `test_a_crashed_lease_holder_does_not_block_the_sweep`, `test_sweep_finishes_…` | pass |
| Redis unavailable | live (D1, real Redis container paused): first response `202` with `redis: failed` and every other store `ok` (6.75 s, request budget bounded), sweep completes after Redis returns (2 attempts, keys gone) — `evidence/l02_deletion_live_D1_redis_outage.json` | pass (LIVE+FIX) |
| Invisible while in progress (list/search) | `test_deletion_in_progress_is_invisible_in_lists_and_search` | pass |
| Audit without content | `test_audit_record_names_the_deletion_not_the_content` | pass |
| Next-turn model context after deletion | `test_next_turn_model_context_excludes_deleted_material` (transcript level) | pass (live-model version: D6 below and journey S9) |
| Retention purge honest | `test_retention_purge_does_not_count_or_release_a_deletion_a_store_failed` | pass |
| Account deletion tombstones sessions | `test_account_deletion_tombstones_every_session_and_reports_partial_honestly` | pass |
| Documents: all retrieval paths, atomic rewrite, honest failure, registry | `tests/test_l02_doc_store_deletion.py` (4) | pass |
| Stale embeddings after document delete | D6 with **real Ollama embeddings** (`nomic-embed-text`, third-party): canary sent before delete, absent from context and sources after (`l02_deletion_live_D6_real_embeddings.json`) | pass (LIVE+REAL) |
| Two workers deleting the same conversation | D2: 5×`200`, one `deletion_id`, then `404` | pass (LIVE+FIX) |
| In-flight generation during deletion | D3: stream ends with `error`, no `done`, 0 turn rows after | pass (LIVE+FIX) |
| Restart during partial cleanup | D4: tombstone written, stores untouched, new process sweep completes | pass (LIVE+FIX) |
| Vector store failure | D5: `202` with `long_term_vector_memory: failed`, others `ok`; retry completes | pass (LIVE+FIX) |
| Temporary-chat closure (L02-01e) | closure and TTL sweep now use the same authoritative workflow; a closed temporary chat keeps its established `409` (`_deleted_for_access` exempts temporary chats); `test_temporary_chat_*` | pass |
| Document `deleting` recovery (L02-02g) | single-document sweep resumes `deleting`/`deletion_failed` documents with bounded retries | pass |

Existing assertions changed (stronger, reason recorded): `tests/test_b_conversations.py` (two tests) previously accepted "deleted conversation readable as empty" (`200`, `total 0`); now require `404` **and** an empty store.

## 5. What "complete" does and does not mean
`complete` = every application-controlled store reported success and the conversation is permanently unreachable. It is **not** a claim of physical or cryptographic erasure. Not covered: host/disk backups and snapshots, any provider-side copy of text sent for inference (none for the local Ollama), the audit log's id-only entries. The vector store reports `RECLAIMED`/`DEFERRED`; `DEFERRED` means the bytes may still be on disk until reclamation.
