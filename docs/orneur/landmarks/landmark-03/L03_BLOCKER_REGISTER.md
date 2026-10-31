# L03 — blocker and limitation register

States: `FIXED` engineering-verified; `BLOCKED` needs a decision or work outside this PR; `OPEN` known and accepted. Nothing is independently qualified (that is Antigravity's gate). Cursor owns MASTER-03 integration; items marked **→ integration owner** are handed over, not done here.

## Fixed in this PR
| ID | Sev | Finding | State |
|---|---|---|---|
| L03-1 | P1 | A blocked Chroma call froze the whole serving process (`/livez` 17.6 s for an 18 s lock); caller timeouts fired 4–12× late (L02-06a) | **FIXED** — chroma runs in a supervised owner process, deadlines on the socket, bounded admission; `/livez` worst 0.02 s |
| L03-2 | P1 | Deleted document text remained on disk after document deletion **and** after conversation deletion (docs vector store never reclaimed; chromadb never purges its log) | **FIXED** — rebuild-without-document, vacuum, orphan-segment removal, collection drop; verified by byte scan |
| L03-3 | P2 | Deleting by collection name could destroy a different conversation's data (prefix collision) | **FIXED** — deletion honours the ownership binding |
| L03-4 | P2 | No vector-layer ownership check (truncated names) | **FIXED (defence in depth)** — bindings, adoption of legacy collections counted |
| L03-5 | P2 | ~4 fds/conversation never released (818 fds at 200) (L02-B4) | **FIXED** for the serving process (constant 4); owner bounded by recycling |
| L03-6 | P2 | Synchronous memory calls on the event loop; `DocStore` opened Chroma and probed Ollama in its constructor; reconciler ran Chroma inside the server | **FIXED** |
| L03-7 | P2 | Explicit remember/recall hid vector failure as success / empty | **FIXED** — truthful `503`/`504` |
| L03-8 | P2 | Deletion states conflated; deferred reclamation for documents not tracked | **FIXED** — separate fields and operator counters |
| L03-9 | P3 | Orphaned HNSW segment directories after `delete_collection`; empty collection left for deleted conversations | **FIXED** |

## Open / blocked
| ID | Sev | Item | State |
|---|---|---|---|
| **L03-B1** | P1 (integration) | **B6 restore does not know the vector owner.** In the isolated PR #143 + L03 merge, a restore over a live directory proceeded while the owner was running, and the running owner kept serving its stale view (a conversation deleted after the backup still counted 1 record) (`evidence/cross_workstream_b6_comparison.json`, X2). With the owner stopped first, B6's restore + L03 behaves correctly: tombstone applied, deleted conversation unreachable, swept, bytes removed (X3). A 12-line patch makes the owner hold B6's serving lock so the restore refuses until it is stopped (X5, `evidence/cross_workstream/proposed_owner_serving_lock.patch`) | **→ integration owner** (Cursor MASTER-03 / B6). Interim: `orca vector stop` before any restore or move of the data directory |
| L03-B2 | P2 | Backup consistency of the vector store: the archive copies the HNSW segment directories as files and the SQLite databases as online-backup snapshots. A quiesced owner is required for a coherent vector backup; a backup taken during writes restored coherently in the one run recorded (X1: 4 collections, counts match SQLite) but that is one sample, not a guarantee | OPEN — stop the owner (or the application) for a vector-consistent backup |
| L03-B3 | P2 | Chromadb's write-ahead log table is never purged for **live** collections: it grows without bound and keeps all text a second time | OPEN — chromadb 1.5.9 behaviour; mitigated only for deletions. A purge/rebuild policy or a different engine is a CTO decision |
| L03-B4 | P2 | Vector **reads** during a foreign write lock are guaranteed only when the owner's interpreter was not frozen; a replaced owner cannot start its client until the foreign lock ends | OPEN — documented in the architecture document; the application is unaffected |
| L03-B5 | P2 | The truncated-id naming remains (`orca_<8>`, `docs_<12>`): false `404`s on new sessions at scale (≈ n / 2³² per new session) come from the ownership layer's prefix claims, not from L03 | **→ ownership-layer owner**: needs semantic memory and keyword files re-keyed too; L03 deliberately did not change names (no data migration) |
| L03-B6 | P2 | The production image installs no chromadb (base dependencies only): the vector subsystem is inactive there and everything runs on the keyword path; enabling it means adding the `memory` extra (dependency/supply-chain review) | BLOCKED — founder/CTO |
| L03-B7 | P3 | POSIX only (Unix sockets, `flock`, `/proc`); other platforms get the embedded transport with no containment | accepted |
| L03-B8 | P3 | Supervisor constants (5 s deadline, 8 s stuck threshold, lane sizes, 1536 MB owner limit) are conservative defaults, not tuned | accepted |
| L03-B9 | P3 | Owner RSS still grows with collections touched (chromadb keeps memory after close); bounded only by the process-restart limit | accepted |
| L03-B10 | P3 | Findings tied to chromadb 1.5.9; a different version can change the lock, log-retention and cross-process behaviour | accepted — re-run the lab on upgrade |
| L03-B11 | P3 | A pre-existing test-order dependence in the memory privacy fixtures (reload without restore) | OPEN, pre-existing, verified on the baseline |
| L03-B12 | P3 | Offline copies and editable ledgers are out of reach of any live deletion; physical erasure of the storage medium is not claimed | by design |
| L03-B13 | – | Not audited: other synchronous HTTP calls (e.g. embedding-service probes) that may run on the event loop in document paths | OPEN — outside the vector scope |

## Counts
Unresolved P0: 0. Unresolved P1: 1 (**L03-B1**, an integration action for the B6/MASTER-03 owner, plus the always-open independent-qualification gate). P2 open: L03-B2…B6. P3 open: B7…B13.
