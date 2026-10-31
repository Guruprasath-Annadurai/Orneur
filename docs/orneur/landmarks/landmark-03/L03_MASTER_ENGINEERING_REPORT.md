# LANDMARK-03 — master engineering report

**Engineering state: `VERIFIED_ENGINEERING` for the independently testable portion — pending only the exact-head CI recorded in `L03_EXACT_HEAD_CI.md`; not independently qualified.** Base: PR #139 branch head `38e0d311991875366f2bc88a39690c7b2b6ea3ee`. Nothing merged, deployed, provisioned or trained; no real customer data or secrets; formal pretraining acceptance remains 0/95. PR #143 (B6), #145 (MASTER-02), #141 and Cursor's MASTER-03 branch were not modified; the B6 comparison ran in a local, unpublished merge worktree.

## What was asked, what was found, what was done
| Phase | Outcome |
|---|---|
| **A — reproduce** | 12 experiments against an exact `38e0d31` checkout with real chromadb 1.5.9 (`L03_BASELINE_DEFECT_REPRODUCTION.md`). **Confirmed:** a held database lock freezes the whole serving process (real server `/livez` 17.6 s for an 18 s lock; caller timeouts fire 4–12× late; the delete budget of 5 s returns after 19.7 s); ~4 descriptors per conversation never released (818 at 200); deleted *document* text stays in `chroma.sqlite3` after document deletion **and** after conversation deletion (chromadb's `embeddings_queue` log is never purged; the docs store was never vacuumed); deleting by collection name can destroy another conversation's data; a worker killed mid-deletion leaves nothing durable at the memory layer. **Not reproduced (stated, not hidden):** concurrent create/delete corruption, crash-during-indexing corruption, and the earlier "cross-process NotFoundError" (chromadb 1.5.9). **Disproved:** the hypothesis that the 8-character collection naming lets another customer read memory through the API (G-006's prefix claims answer `404`); it is a library-level defect and an availability-at-scale issue handed to the ownership-layer owner |
| **B — isolation** | Selected: one supervised **owner process** per data directory over a private Unix socket; deadlines enforced on the socket; separate bounded read/write lanes; per-conversation caps; supervisor that kills and replaces an unresponsive owner. Rejected: embedded threads, per-operation / per-conversation processes. **BLOCKED for CTO/founder:** switching vector backend (data-format migration) — comparison in `L03_VECTOR_ISOLATION_ARCHITECTURE.md` |
| **C — resources** | Serving process: constant 4 descriptors and 44 MB regardless of conversation count (baseline 818 fds / 665 MB at 200). Owner: bounded descriptors by recycling (count and descriptor pressure). **Total memory is not lower** (684 vs 665 MB); stated plainly. Admission, backpressure and per-conversation isolation measured (`L03_RESOURCE_AND_FD_BENCHMARKS.md`) |
| **D — lifecycle** | Access revoked / collection removed / bytes reclaimed / cleanup pending are separate, reported and counted. True per-document erasure (rebuild without the document + vacuum + orphan-segment removal); conversation deletion drops the document collection; deletion by name honours ownership; tombstone gate in the vector layer; interrupted rebuild self-heals. B6 compared in isolation (`L03_DATA_LIFECYCLE_AND_ERASURE_EVIDENCE.md`, blocker L03-B1) |
| **E — RAG** | Registry authority, document identity, lexical/dense merge, stale-dimension fallback, injection/tool gates and quota/commit semantics re-tested after the lifecycle changes: green. A vector outage degrades to the same conversation's keyword index, never to another's data |
| **F — failure lab** | 10 required scenarios + the stall/frozen-owner/limit/idle cases, both refusal and recovery asserted, on two real workers (`L03_MULTIWORKER_FAILURE_MATRIX.md`) |
| **G — regression / CI** | See `L03_SECURITY_REGRESSION_RESULTS.md` and `L03_EXACT_HEAD_CI.md` (every failed run and its cause is kept) |

## Headline measurements (same workstation, before → after)
| Measurement | Baseline `38e0d31` | This branch |
|---|---|---|
| Real server `/livez` worst latency while the vector database is write-locked 18 s | **17.61 s** | **0.02 s** (62 probes) |
| Write blocked behind the lock: caller released after (5 s deadline) | 17.6 s (no deadline possible) | **5.02 s**, truthful `504`/`503` |
| Deletion with a 5 s budget under the lock | 19.72 s | request returns `202` (revoked, retryable) while probes stay at 0.02 s |
| Serving-process descriptors at 200 conversations | **818** | **4** |
| Serving-process RSS at 200 conversations | 665 MB | 44 MB (owner 640 MB; **sum not lower**) |
| Per-conversation recall latency p50 / p95 (200 conversations) | 0.249 / 0.300 s | 0.25 / 0.304 s |
| Deleted document text on disk after deletion | present (4 occurrences) | absent (0) |
| Owner crash → first success | n/a | median 0.48 s (kill), ~6.9 s (frozen) |

## Material findings made along the way
Chromadb never purges its write-ahead log (deleted text persists; the table grows without bound); `delete_collection` leaves segment directories; a hot conversation's refusals must be made in the client or they starve others; a flat deadline refuses legitimate bulk indexing on a slow runner (found by CI — the deadline now scales with the batch); the owner's start-up and first-embed cost must not be paid inside a request deadline (warm-up); `Collection` handles must never re-create (stale writes); a rebuild has one crash window, closed and tested.

## Honest limits (full list: `L03_BLOCKER_REGISTER.md`)
A foreign write lock still prevents a *new* owner from initialising, so vector reads can wait (the application cannot); the owner is a single point of failure for vector features; POSIX only; the production container image installs no chromadb so this subsystem is inactive there until the `memory` extra is approved; chromadb's log is never purged for live collections; offline copies and editable ledgers are beyond live deletion; findings are tied to chromadb 1.5.9; B6's restore does not yet stop the vector owner (**→ integration owner**).

## Cross-workstream implications (for Cursor / MASTER-03 integration)
1. **B6 restore must stop the vector owner** (or the owner must hold B6's serving lock): demonstrated hazard and a 12-line patch that works (X2/X5). 2. B6's `_apply_deletions` tombstones + L03's tombstone gate + the conversation sweep give the correct end state after a restore (X3). 3. The new sidecar `orneur_bindings.sqlite` and `pending_reclamation.json` live in the backed-up vector directories and are included by B6 (X4). 4. `orca vector status|stop` and `/readyz → dependencies.vector` are new operator surfaces. 5. `ORNEUR_VECTOR_*` environment variables are new configuration.

## Independent qualification
Instructions, reproduction commands, attack matrix and what we did not try: `L03_ANTIGRAVITY_HANDOFF.md`.
