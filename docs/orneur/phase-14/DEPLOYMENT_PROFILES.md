# Phase 14 §1 — ORNEUR Deployment Profiles

Two officially supported profiles, as required by the governing spec.
Both are real today — SOVEREIGN was already the de facto only profile
before this phase; DISTRIBUTED's foundational piece (the authority
backend) is built and tested this phase (see `AUTHORITY_DISTRIBUTION.md`).

**Phase 14A.3**: the profile itself is now an explicit, validated
configuration value (`ORNEUR_DEPLOYMENT_PROFILE`,
`orca/godmode/deployment_profile.py`) rather than something inferred
from "does a Postgres URL happen to exist." This closes a real,
disclosed hazard from Phase 14A.2's own closure: DISTRIBUTED mode used
to silently fall back to SOVEREIGN's per-host file-based security root
if `ORNEUR_SECURITY_ROOT_DATABASE_URL` was left unset. That fallback is
now structurally impossible — see `SECURITY_ROOT.md`'s Phase 14A.3
addendum.

## ORNEUR SOVEREIGN

- Single host (or a local cluster sharing one filesystem).
- `ORCA_HOME` on local disk, SQLite everywhere: Godmode leases
  (`orca/godmode/lease_store.py`), auth (`orca/auth/db.py`), memory,
  registries, and the security root (`~/.orneur-security-root`).
- `ORNEUR_DEPLOYMENT_PROFILE` unset, or explicitly `SOVEREIGN` — this
  is the default, so every existing developer/self-hosted/offline
  deployment continues to work with zero configuration changes.
- This is the zero-setup, "one install, one machine, private/local
  deployment" profile the spec requires it to remain.
- Every Phase 13.2/13.3 SQLite-path guarantee (cross-process atomicity
  on one host, real SIGKILL crash consistency) applies unchanged.

## ORNEUR DISTRIBUTED

- Multiple API/worker processes, potentially multiple hosts.
- **Must be explicitly declared**: `ORNEUR_DEPLOYMENT_PROFILE=DISTRIBUTED`.
  An unrecognized value fails startup immediately (spec §5).
- **Required, validated at startup, no silent fallback** (spec §1-3,
  §6 — enforced in `orca/godmode/deployment_profile.py`, called from
  `orca/serve/api.py` at module import time, and from
  `security_root._backend()`/`lease_store._backend()` themselves so
  the enforcement cannot be bypassed by skipping a separate validation
  step):
  - `ORNEUR_GODMODE_DATABASE_URL` (PostgreSQL) — the Godmode authority
    store. Missing, empty, malformed, or unreachable at startup ⇒ the
    process never becomes ready (`DeploymentConfigError` raised at
    import time). Without this enforcement, each host would maintain
    an independent `leases.db`, silently reintroducing the exact
    authority-multiplication class of bug Phase 13 fixed (see
    `AUTHORITY_DISTRIBUTION.md`).
  - `ORNEUR_SECURITY_ROOT_DATABASE_URL` (PostgreSQL) — a **separate
    database** from `ORNEUR_GODMODE_DATABASE_URL` for the independent
    security root (`orca/godmode/security_root.py`). Same fail-startup
    enforcement — DISTRIBUTED mode can no longer silently fall back to
    a per-host file. See `SECURITY_ROOT.md`.
  - `ORNEUR_DATABASE_URL` (PostgreSQL) — user/session/audit state
    (`orca/auth/db.py`). **Phase 14A.4**: now given the exact same
    fail-startup enforcement as the two backends above — missing,
    empty, malformed, or unreachable at startup fails the process
    before it ever serves traffic. Enforced both in
    `validate_deployment_config()` (the primary gate, at
    `orca/serve/api.py`'s import time) and inside `orca/auth/db.py`
    itself (defense in depth for any other entry point that imports it
    directly). See `STATE_OWNERSHIP.md`'s Phase 14A.4 addendum for the
    full per-table audit of what this connection string owns.
  - `ORNEUR_REDIS_URL` — cross-instance chat session continuity
    (`orca/serve/session_store.py`) and shared rate-limit counters
    (`orca/serve/ratelimit.py`), both already dual-backend from before
    this phase, now proven under real multi-process load (see
    `MULTI_WORKER.md`).
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
