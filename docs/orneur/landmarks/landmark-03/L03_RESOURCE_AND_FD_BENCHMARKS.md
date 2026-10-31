# L03 Phase C — resource and descriptor measurements

Same workstation, Python 3.11.18, chromadb 1.5.9, SQLite 3.53.1, 16 CPUs, WSL2, and the **same workload** before and after: for N sessions, build `LongTermMemory(sid)`, store one item, recall once. Baseline taken from an exact checkout of `38e0d31` (`evidence/baseline/l03_baseline_results_38e0d31.json`, experiment E3_E8); after-change numbers from `evidence/after/l03_bench_results.json` (script `l03_bench.py`, product SHA recorded in the file). These are measurements of one run each on a workstation; **no capacity target is claimed or met by them**.

## Descriptors and memory (workload above)
| Sessions | Baseline fds (process) | Baseline RSS | After: application fds | After: application RSS | After: owner fds | After: owner RSS | Owner client recycles |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 | 55 (5.1/session) | 179 MB | **4** | **44 MB** | 58 | 293 MB | 0 |
| 50 | 216 (4.24) | 283 MB | 4 | 44 MB | 93 | 366 MB | 1 |
| 100 | 416 (4.12) | 410 MB | 4 | 44 MB | 35 | 436 MB | 3 |
| 200 | **818 (4.07)** | **665 MB** | 4 | 44 MB | 51 | 553 MB | 6 |
* Descriptors: baseline grows linearly (~4 per conversation, never released). After: the application process holds a constant 4; the owner's count is bounded by recycling (it closes and reopens its chroma client above 32 open collections or 70 % of its descriptor limit, which releases every descriptor — measured separately: 256 → 12 fds on `client.close()`). With the owner's soft limit capped at 120 descriptors, 80 conversations produced **0 failed operations** (`tests/test_l03_failure_lab.py`).
* Memory: **not materially reduced overall.** Chroma does not return memory when collections are closed (RSS unchanged after `close()`), so the owner's RSS still grows with the number of collections touched (293 → 553 MB for 10 → 200). What changed is where it lives: the serving process stays at 44 MB. The owner leaves and restarts above a configurable limit (default 1536 MB; tested with 150 MB) because only a new process releases it. Baseline total 665 MB vs after total 597 MB at 200 sessions (−10 %, within what the allocator noise of one run can explain; do not read it as a gain).
* Embedded mode after the change (recycling on): 47 fds / 415 MB at 200 sessions, a side benefit of the same recycling for non-server uses.

## Latency (per session: construct + store + recall, includes first-collection creation)
| Sessions | Baseline p50 / p95 (s) | After (service) p50 / p95 / max (s) |
|---:|---|---|
| 10 | 0.24 / 0.28 | 0.298 / 0.33 / 0.86 |
| 50 | 0.247 / 0.284 | 0.267 / 0.312 / 0.86 |
| 100 | 0.245 / 0.287 | 0.263 / 0.316 / 0.84 |
| 200 | 0.249 / 0.300 | 0.258 / 0.309 / 0.90 |
The socket hop adds ≈ 10–20 ms at p50; the 0.86 s maximum is the one-off cost of starting the owner (cold start ≈ 0.5–0.9 s). Errors in these runs: 0.

## Behaviour under faults (`evidence/after/l03_faults_bench_results.json`, one run)
| Measurement | Baseline | After |
|---|---|---|
| Real server `/livez` while the shared vector database is write-locked 18 s (`l03_server_stall_probe.py`) | worst **17.61 s** (9 probes); every request 17.6 s | worst **0.02 s** (62 probes) |
| Write blocked behind the lock: time until the caller is released (5 s deadline) | 17.6 s (no deadline possible) | **5.02 s**, `504 request_timeout` / `503 server_busy` |
| Deletion with a 5 s budget under the lock | returned after 19.72 s | the cascade finishes in a worker thread; the request returns `202` (access revoked, retryable) while probes stay at 0.02 s |
| Write blocked behind the lock, 3 s deadline, 5 trials | n/a | released at 3.0 s each time (`VectorTimeout`) |
| Owner `SIGKILL` → first successful operation | n/a (no separate owner) | median **0.475 s**, max 0.49 s (8 trials) |
| Owner frozen (`SIGSTOP`) → first successful operation | whole process frozen | **6.9 s** (3 trials: probe, kill, restart) |
| 64 threads hammering one collection for 6 s | unbounded | 53 served, **33 371 refused immediately** (`busy`, p50 latency 2 ms, p99 0.16 s); a different collection stays served (`test_one_conversation_cannot_monopolise_the_service`) |
| Active-operation limits | none | in-flight read 8 / write 3, waiting 16 (≤ 2 s), per-collection 2, owner queues 32 per lane, owner connections 64 |

## Counters exposed (no user content)
`/readyz` → `dependencies.vector`: mode, whether deadlines are enforced, owner status (`pid`, queue depth, running jobs, oldest running job age, fds, RSS, open collections, client recycles, refusal counts), client counters (calls, ok, timeouts, busy, owner starts/kills) and latency percentiles; `orca vector status` prints the same. `maintenance_backlog.vector_deletions_unconfirmed` and `vector_reclamation_pending` count cleanup that is known to be incomplete. In-process degradation counters (`dropped_writes`, `empty_recalls`, `ownership_refusals`) are in `orca.brain.memory.vector_memory_counters()`.

## Caveats
One workstation, one run per cell, WSL2 (file-system and `flock` behaviour may differ on production hosts). The baseline per-session figures vary by ±0.1 fd between runs. RSS is read from `/proc/self/statm`. The faults benchmark measures the supervisor's policy constants (probe delay 0.2 s, two 1.5 s pings, 8 s stuck threshold), which are not tuned.
