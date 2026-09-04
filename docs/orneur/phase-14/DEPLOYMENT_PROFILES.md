# Phase 14 §1 — ORNEUR Deployment Profiles

Two officially supported profiles, as required by the governing spec.
Both are real today — SOVEREIGN was already the de facto only profile
before this phase; DISTRIBUTED's foundational piece (the authority
backend) is built and tested this phase (see `AUTHORITY_DISTRIBUTION.md`).

## ORNEUR SOVEREIGN

- Single host (or a local cluster sharing one filesystem).
- `ORCA_HOME` on local disk, SQLite everywhere: Godmode leases
  (`orca/godmode/lease_store.py`), auth (`orca/auth/db.py`), memory,
  registries.
- No `ORNEUR_GODMODE_DATABASE_URL`, no `ORNEUR_DATABASE_URL`, no
  `ORNEUR_REDIS_URL` set — every store defaults to its file-backed form.
- This is the zero-setup, "one install, one machine, private/local
  deployment" profile the spec requires it to remain.
- Every Phase 13.2/13.3 SQLite-path guarantee (cross-process atomicity
  on one host, real SIGKILL crash consistency) applies unchanged.

## ORNEUR DISTRIBUTED

- Multiple API/worker processes, potentially multiple hosts.
- **Required** environment for correctness once more than one host is
  involved:
  - `ORNEUR_GODMODE_DATABASE_URL` (PostgreSQL) — the Godmode authority
    store. Without this, each host would maintain an independent
    `leases.db`, silently reintroducing the exact authority-
    multiplication class of bug Phase 13 fixed (see
    `AUTHORITY_DISTRIBUTION.md`).
  - `ORNEUR_DATABASE_URL` (PostgreSQL) — user/session/audit state
    (`orca/auth/db.py`), already dual-backend from before this phase.
  - `ORNEUR_REDIS_URL` — cross-instance chat session continuity
    (`orca/serve/session_store.py`) and shared rate-limit counters
    (`orca/serve/ratelimit.py`), both already dual-backend from before
    this phase, now proven under real multi-process load (see
    `MULTI_WORKER.md`).
  - `ORNEUR_SECURITY_ROOT_DATABASE_URL` (Phase 14A.2, PostgreSQL) — a
    **separate database** from `ORNEUR_GODMODE_DATABASE_URL` for the
    independent security root (`orca/godmode/security_root.py`).
    Without this, DISTRIBUTED mode falls back to the SOVEREIGN
    file-based security root per host, which does NOT give cross-host
    kill-switch visibility — a real, disclosed limitation for any
    genuinely multi-host DISTRIBUTED deployment that skips this
    variable. See `SECURITY_ROOT.md`.
- **Known-remaining single-host-shaped stores** (from
  `CURRENT_DEPLOYMENT_ARCHITECTURE.md`'s audit) that DISTRIBUTED mode
  does not yet solve, and must not be assumed solved: the gateway
  worker registry (`orca/gateway/worker.py`, plain JSON files, no
  locking), episodic/semantic memory (`orca/memory/*.py`), the model/
  checkpoint/dataset registries (`orca/registry/*.py`), the lens job
  queue, governance model cards, and license state. Running DISTRIBUTED
  today requires either (a) a shared network filesystem for `ORCA_HOME`
  covering these specific stores (fragile — most of their writer paths
  have no file locking or atomic rename), or (b) promoting each to the
  same DB/Redis pattern already proven for auth, sessions, rate limits,
  and now Godmode. **(b) is the recommended direction; it is explicitly
  out of scope for this phase** — Phase 14 closes the single highest-
  risk gap (authority) and documents the rest honestly rather than
  claiming a broader migration that was not done.

## Choosing a profile

| | SOVEREIGN | DISTRIBUTED |
|---|---|---|
| Hosts | 1 | 2+ |
| Godmode backend | SQLite | PostgreSQL |
| Auth backend | SQLite | PostgreSQL |
| Sessions/rate-limit | in-process | Redis |
| Setup | zero-config | requires 3 connection strings + the known-remaining stores addressed operationally |
| Use case | self-hosted, private, single-operator | cloud production behind a load balancer |

Nothing in the codebase auto-detects or switches profile — it is
entirely a function of which `ORNEUR_*_URL` environment variables an
operator sets, exactly matching the existing `orca.auth.db` precedent.
