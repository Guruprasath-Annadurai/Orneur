# L02-06 — Operational readiness

Evidence state: **VERIFIED_ENGINEERING** on one workstation. **No capacity, latency or availability figure below is a claim about production**; every number is a measurement from the stated environment (16 CPU, 15.5 GB RAM, WSL2, Python 3.11, fixture provider unless stated) and is reproduced in `evidence/l02_ops_live_*.json`.

Code: `orca/serve/ops.py`, `orca/serve/{backup,metrics,errors}.py`, `orca/serve/api.py` (probes, drain middleware, admission, deadline), `orca/cli.py` (graceful server, `data-backup`). Tests: `tests/test_l02_operational.py` (13), `tests/journey/test_l02_operations_live.py` (O1–O8).

## Probes
| Endpoint | Meaning |
|---|---|
| `/livez` | process answers |
| `/readyz` | 503 when: transcript store unreadable, disk below critical headroom, file descriptors near the limit (~90 %), draining, stream slots exhausted/backlog; Redis is **advisory** (reported, never fatal – SQLite is authority); Redis ping bounded to 1 s (an unbounded ping held `/readyz` 5 s when Redis was frozen) |
| `/healthz` | existing detailed report (no user content) |
| `/api/admin/metrics` | bounded event counters (turn outcomes, cancellations, deletions, refusals, reconciler) – no user content |

## Behaviours and measurements
| Scenario | Result (file) |
|---|---|
| Cold start, empty data dir | `/livez` 0.55–0.73 s, `/readyz` 0.58–0.87 s, idle RSS 75–92 MB (O1) |
| SIGTERM with 3 s grace | exit 3.19 s after signal; new work → `503 server_draining`; `/readyz` 503; cut stream recorded `not_committed/server_shutdown`; DB integrity ok (O2) |
| 24 concurrent streams, cap in force | 20 completed and saved, 4 refused `server_busy` (was `backend_error` before this work); median 5.99 s, max 12.7 s; RSS idle 126→peak 350→after 262 MB; fds 44→131→127; slots in use after: 0 (O3) |
| Saturation, capacity 3 | 3 completed, 7 `server_busy`, **3 quota units spent** (refused work not charged) (O4) |
| Model backend unavailable | turn refused with `model_unavailable` in 0.07 s; `/readyz` turns 503 only after up to 15 s (model-list cache TTL) – a known lag (register L02-B9); refund-on-failure is proven by the quota suites, not by this file (O5) |
| `kill -9` mid-turn then restart | restart→ready 0.57 s, integrity ok, committed turn survived, mid-turn `not_committed/worker_lost`, retry committed (O6) |
| Low disk | warn/critical thresholds `DISK_WARN_MB`=1024 / `DISK_CRITICAL_MB`=128 (env-configurable); with a simulated critical threshold `/readyz`=503 and a new turn is refused `history_unavailable` with 0 quota units spent; a genuinely full disk was **not** created (O7) |
| Redis interruption | `/readyz` stays 200 (1.01 s, bounded ping), Redis reported `unavailable`/advisory, a turn during the outage completes and is saved, Redis recovers (O8) |
| Total stream deadline | `request_timeout`, nothing saved |

Defects found and fixed while measuring: fd leak from duplicate diskcache copies (shared `SemanticMemory` cache; remaining ≈3.5 fds per active conversation come from per-conversation vector indices and are *documented, not removed*); unbounded Redis ping in readiness; Kernel stream path had no admission cap; capacity errors reported as `backend_error`.

## Backup and restore
`orca data-backup create <empty dir>` (SQLite online-backup API, hashed manifest), `verify <dir>` (re-hash + `PRAGMA integrity_check`), `restore <dir> [--overwrite]` (verifies first; refuses a non-empty target without the flag; stop the server first). Tests: `tests/test_l02_operational.py` (round-trip, tamper detection, refusal). A backup is an **unencrypted copy of user data**; deleting a conversation does not remove it from existing backups (disclosed in the deletion response). The older `orca backup --keep N` (auth DB) is unchanged – an earlier commit accidentally shadowed it; fixed and pinned by a test.

## Runbooks (symptom → first action)
* **`/readyz` 503, `draining`** – expected during shutdown/rolling restart; wait for exit.
* **503 `server_busy` rate rising** – stream cap reached; reduce load or raise the cap deliberately after measuring; do not raise it blindly (fd and RSS grow per stream, see O3).
* **`/readyz` 503, disk** – free space or move the data dir; do not restart (writes will keep failing).
* **`/readyz` 503, fds** – check open conversations; restart is a safe recovery (`kill -9` path is tested, O6).
* **Redis down** – no action required for correctness; restore for cross-worker advisory locking.
* **Crash/restart** – outcomes of in-flight turns resolve to `not_committed(worker_lost)`; clients retry with the same key.
* **Restore** – stop server → `data-backup verify` → `data-backup restore` → start → check `/readyz`.
* **Reconciler blocked items** – `GET /api/admin/reconcile`; items quarantined, not deleted, until reviewed.

## Not established
Sustained-load behaviour, multi-host behaviour, production proxy/SSE buffering, real disk-full behaviour, backup scheduling/encryption/off-host storage, any SLO. Known issue L02-06a: a held Chroma lock can freeze the whole process because the library holds the GIL (`evidence/l02_chroma_lock_freezes_process.txt`); mitigated only by bounded callers elsewhere.
