# L03 Phase A — baseline defect reproduction

Baseline: PR #139 head `38e0d311991875366f2bc88a39690c7b2b6ea3ee` (product code taken from an exact checkout; the lab asserts that `orca` is imported from that checkout and records the SHA). Real `chromadb` 1.5.9, SQLite 3.53.1, Python 3.11.18, one workstation (16 CPUs, WSL2). Disposable data directories, synthetic data. Nothing in the product was changed before these were captured.
Reproduce: `L03_REPO=<checkout of 38e0d31> python docs/orneur/landmarks/landmark-03/evidence/baseline/l03_baseline_lab.py [E1 … E12]` → `evidence/baseline/l03_baseline_results_38e0d31.json` (E1–E11) and `l03_baseline_e12_38e0d31.json`; the real-server probe is `evidence/l03_server_stall_probe.py` → `evidence/baseline/l03_server_stall_38e0d31.json`.

## Where Chroma is used (code inspection)
`orca/brain/memory.py` `LongTermMemory` (one `PersistentClient` **per instance**, collection `orca_<session_id[:8]>`; delete/vacuum in a one-thread executor with a `Future.result(timeout)` budget), `orca/docs/store.py` `DocStore` (own client, collection `docs_<first 12 chars sans dashes>`; opened **in the constructor**, i.e. while a request builds a session), `orca/serve/deletions.py` (a third client for the "is the collection provably absent" probe), `orca/gateway/reconcile.py` (a fourth, inside the serving process, in the periodic sweep). Memory calls were made synchronously from async handlers (`recall_context`, `commit_to_long_term`). Collections are named by a **truncated session id**.

## The ten required conditions
| # | Condition | Result on the baseline | Evidence |
|---|---|---|---|
| 1 | Held SQLite/Chroma write lock | **CONFIRMED, intermittent whole-process freeze.** A client construction + write blocked in 3 of 3 trials; in 2 of 3 trials the **entire interpreter** was frozen (heartbeat thread gap 13.5 s ≈ the lock time), in 1 only the calling thread. A write on an already-open collection completed. A real `orca serve` (18 s lock): `/livez` answered after **17.6 s**, every request took 17.6 s | E1; `baseline/l03_server_stall_38e0d31.json` |
| 2 | Concurrent collection creation/deletion | **Not reproduced** — 64/64 operations across 8 threads, no errors | E2 |
| 3 | Many sessions sharing persistent storage | Works, but costs **4.07–5.1 file descriptors and ~3.3 MB RSS per session** (818 fds / 665 MB at 200 sessions); and two session ids with the same first 8 characters **share a collection** | E3_E8, E11 |
| 4 | Worker timeout during Chroma deletion | **CONFIRMED.** `delete_session` with a 5.0 s budget returned after **19.72 s** (4×), result `logical_deleted=False, PENDING`; heartbeat frozen 19.45 s | E4 |
| 5 | Cancellation during retrieval | **CONFIRMED.** A caller's 1.0 s timeout fired after **11.9 s** (the event loop itself was frozen); the worker thread cannot be cancelled | E5 |
| 6 | Process crash during indexing | **Not reproduced as a defect** — `kill -9` mid-indexing: `integrity_check ok`, store reopens, writes work | E6 |
| 7 | Restart after interrupted deletion | **CONFIRMED gap.** A worker killed mid-deletion leaves the data retrievable by the memory layer and records **nothing durable at that layer**; only the conversation tombstone protects it | E7 |
| 8 | High active-session count / descriptor growth | **CONFIRMED** — see row 3; descriptors never fall until the process exits | E3_E8 |
| 9 | Second worker reading data created by the first | **Earlier "cross-process NotFoundError" finding NOT reproduced on chromadb 1.5.9** (fresh process after the creator exits; an open client reading a collection created later by another process; two processes writing one collection → 80/80) | E9 |
| 10 | Deleted data remaining in shared pages | Conversation memory: **no residue** after delete + VACUUM, but the deleted collection's **segment directory stays on disk**. **Documents: CONFIRMED** — after `delete_doc_detailed` *and after the whole-conversation cascade* the deleted text is still in `chroma.sqlite3` (4 occurrences), because the document vector store is never vacuumed **and** chromadb retains the original add in its `embeddings_queue` log table (it never purges it: 33 adds → 33 rows); an empty collection is also left behind for a deleted conversation | E10, E12 |

## Hypotheses tested and disproved (recorded so they are not re-opened)
* **"Another customer can read a conversation's memory through a session id sharing its first 8 characters" — not exploitable through the API.** At the library level it is real (E11: the second session recalled the first's text and its deletion destroyed it), but G-006's storage-prefix claims make the API answer `404` to the second session (observed while building the API-level reproduction). The remaining effect of the truncated naming is **false refusals at scale**: 8 hex characters are 32 bits, so a legitimate new session collides with one of `n` existing sessions with probability ≈ n / 2³² (0.023 % per new session at 1 million existing, 0.23 % at 10 million; the first collision somewhere among all sessions is expected after ~77 k sessions). The affected customer gets `404 session not found` on a brand-new conversation. That is a P2 finding left for the owner of the ownership layer (it needs semantic memory re-keyed as well); L03 adds the vector-layer defence in depth described in the architecture document.
* **Cross-process collection visibility** — see row 9.
* **Concurrent create/delete corruption** and **crash-during-indexing corruption** — see rows 2, 6.

## Findings that exist only because the lab looked at disk
* Chromadb 1.5.9 embedded **never purges `embeddings_queue`**: deleted records' text persists indefinitely after `delete(where=…)`, and the table grows without bound (one row per add, forever).
* `delete_collection` leaves the collection's HNSW segment directory behind.
* The document vector database had no reclamation of any kind.
