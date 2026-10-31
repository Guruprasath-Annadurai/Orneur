# L03 Phase F — multi-worker failure and recovery matrix

Real `orca serve` workers (two processes sharing one data directory), the real vector-service owner, real chromadb. "Expected refusal" and "successful recovery" are both asserted. A missing optional dependency (chromadb) is a **failure** in these files (module-level assert), never a skip or a keyword-fallback pass. Sources: `tests/journey/test_l03_vector_live.py` (V1–V6, evidence `evidence/l03_vector_live.json`), `tests/test_l03_vector_service.py`, `tests/test_l03_failure_lab.py`, `tests/test_l03_lifecycle.py`.

| # | Required scenario | Test | Expected refusal | Recovery / result |
|---|---|---|---|---|
| 1 | Two workers, one data directory | V1 | — | exactly **one** owner for both; worker B recalled what worker A wrote; neither application process mapped the chromadb library |
| 2 | Concurrent read/write/delete | `test_two_workers_deleting_…`, `test_one_conversation_cannot_monopolise_the_service`, flood benchmark | per-collection cap → `busy` | other conversations stay served; deletion converges |
| 3 | SIGTERM during retrieval | V4 | the in-flight call is bounded by its deadline | worker B and the owner unaffected (owner PID unchanged); worker A exits and is restarted |
| 4 | SIGKILL during indexing | `test_killing_the_owner_mid_indexing_…`, V3, faults bench | calls in flight fail (`VectorUnavailable`) | SQLite `integrity_check ok`; next call restarts the owner (median 0.475 s); writes work again |
| 5 | Corrupted / partially written metadata | `test_a_damaged_binding_database_fails_closed…`, `test_a_collection_without_a_binding_is_adopted_once…` | damaged ownership record → nothing served, nothing written (`recall → []`, strict → error) | repaired file → service resumes; legacy collection adopted once then protected |
| 6 | Expired resource ownership | `test_a_lease_holder_that_died_after_removing_the_collection_…` | — | expired deletion lease taken over; remaining reclamation completed; `RECLAIMED`; no residue |
| 7 | Retry after a worker disappears | V3/V4, `test_a_crash_after_access_revocation_…` | unreachable until swept | the sweep or the next request completes the work |
| 8 | Missing embeddings service | `test_the_embedding_service_being_absent_does_not_lose_or_leak_documents` | — | chroma's default embedder indexes; each conversation retrieves only its own document |
| 9 | High file-descriptor pressure | V5 (80 conversations, owner `max_open` 16), `test_high_descriptor_pressure_…` (owner limit 120), `…_recycles_on_pressure_even_when_the_collection_limit_is_effectively_off` | — | 0 failed operations; application fds 28 → 24, owner 31 → 78 (bounded); recycling by count **and** by descriptor pressure |
| 10 | Customers with conflicting names/ids | `test_customers_with_the_same_filename_and_the_same_document_id_text_stay_separate`, collision tests | colliding conversation refused | neither sees nor deletes the other's chunks |
| + | Held database lock (the L02-06a fault) | `test_a_write_blocked_behind_a_held_lock_…`, `test_writes_stuck_…`, V2, stall probe | write refused at its deadline with `504 request_timeout`/`503 server_busy`; further writes refused immediately | application heartbeat gap 0.0 s; probes ≤ 0.53 s; after the lock ends the service answers reads and writes |
| + | Frozen owner (`SIGSTOP`) | `test_a_stalled_owner_that_cannot_answer_a_ping_is_killed_and_replaced` | first calls fail within the deadline | supervisor kills and replaces it; data intact; the frozen PID is gone |
| + | Owner memory above its limit | `test_an_owner_whose_memory_passes_its_limit_…` | — | leaves when idle, next call starts a fresh one, data intact |
| + | Idle owner | `test_the_owner_exits_by_itself_when_idle…` | — | no process left holding the directory |
| + | Admission flood | `test_admission_is_bounded_…` | `VectorBusy` immediately (< 1.5 s), never a hang | all 40 callers returned within 12 s |
| + | Auth / path | `test_a_request_without_the_token_…` | wrong token → `auth`; root outside the data directory → refused | socket 0600, run directory 0700 |

## Distinguishing product failures from unsupported environments
* chromadb missing → the module asserts (failure). Docker or Redis are not needed by any of these tests. `pgrep`, Unix sockets and `/proc` are (Linux; the owner is POSIX-only by design — non-POSIX uses the embedded transport and the containment claim does not apply).
* Timing assertions use generous bounds (a refusal "within the deadline + 1.5 s", probes < 2 s) so a loaded CI host does not turn a pass into a flake; the recorded figures are in the benchmark document.
* The one scenario whose outcome depends on chance — whether a blocked native write freezes the owner's *interpreter* (≈ 1 in 3 at baseline) — is asserted only for what holds either way (bounded release, no hang, recovery when the lock ends) and the dependence is documented in the architecture document.

## Not covered
Multi-host deployments, NFS, a reverse proxy in front of the workers, more than two workers, sustained load beyond the measured flood, a real KMS/HSM, kernel OOM-kill of the owner (an owner `SIGKILL` is covered, the OOM trigger is not).
