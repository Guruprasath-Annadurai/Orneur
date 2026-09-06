# Phase 14 §6 — Formal State Ownership Catalog

This formalizes `CURRENT_DEPLOYMENT_ARCHITECTURE.md`'s audit into the
owner/readers/writers/consistency/persistence/recovery/backup shape the
spec requires, for every state category §6 names explicitly.

| State | Owner (backend) | Readers | Writers | Consistency | Persistence | Recovery | Backup requirement |
|---|---|---|---|---|---|---|---|
| Godmode leases | SQLite (SOVEREIGN) or PostgreSQL (DISTRIBUTED) | resolution.py, connector_elevation.py, delegation.py | issuance.py, lease_store.py's consume_use/revoke/reserve_uses | Strict (transactional, `BEGIN IMMEDIATE` or `SELECT...FOR UPDATE`) | Durable | Reconciled via `revocation_ledger.py` after any restore -- **mandatory**, see `BACKUP_AND_RECOVERY.md` | Yes -- critical, sensitive (contains capability grants) |
| Security root (Phase 14A.2, GROUND TRUTH) | Separate SQLite file outside `ORCA_HOME` (`~/.orneur-security-root`, SOVEREIGN) or a separate Postgres database (DISTRIBUTED) | `kill_switch.is_active()`/`status()` -- the ONLY function every elevated-authorization gate consults | `security_root.advance()`, called by `kill_switch.activate()`/`deactivate()` | Strict (transactional), monotonic epoch, never cached | Durable, structurally outside the ordinary ORCA_HOME/authority-database backup unit | This IS the recovery-proof source of truth -- never itself reconciled FROM anything else | Yes -- its own explicit disaster-recovery procedure, deliberately NEVER bundled with an ordinary ORCA_HOME or authority-database backup (see `BACKUP_AND_RECOVERY.md`'s backup classification) |
| Kill switch (leases.db mirror) | Same authority database as leases (SQLite table for SOVEREIGN, Postgres table for DISTRIBUTED) as of Phase 14A.1 | `/readyz`'s authority_store reporting, `kill_switch.status()`'s activated_at/reason display fields | godmode/kill_switch.py's activate/deactivate (via lease_store's ks_get_state/ks_set_state), written AFTER the security root per crash-safety ordering | Strict (transactional), cross-worker-visible in DISTRIBUTED | Durable | No longer the security boundary (Phase 14A.2) -- still reconciled via `kill_switch_ledger.py`'s `reconcile_after_restore()` as defense-in-depth, see `KILL_SWITCH_DURABILITY.md` | Yes, same criticality as leases -- but its own staleness is no longer a security event, only a display-consistency one |
| Kill-switch event ledger | Append-only JSONL file, deliberately independent of the kill_switch_state table's backup unit | `kill_switch_ledger.py`'s `reconcile_after_restore()` | `kill_switch.activate()`/`deactivate()` | Append-only, eventually-consistent is fine | Durable, ideally on independently-backed-up storage | Defense-in-depth for the mirror's own consistency (Phase 14A.2: the security root is the actual recovery guarantee) | Yes -- same criticality as the revocation ledger |
| Revocation ledger | Append-only JSONL file, deliberately independent of the leases table's backup unit | `revocation_ledger.py`'s `reconcile_after_restore()` | `lease_store.revoke()` | Append-only, eventually-consistent is fine (it is a durable log, not a live-decision store) | Durable, ideally on independently-backed-up storage (see limitation in `revocation_ledger.py`'s own docstring) | This IS the recovery mechanism for leases | Yes -- must be backed up on a cadence at least as frequent as, and ideally independent from, the leases table |
| Approvals (`GodmodeApproval`) | Ephemeral -- never persisted independently | issuance.py (folds fields into the issued lease) | n/a | n/a | None | n/a | No |
| Model registry | JSON file (SOVEREIGN); not yet distributed | gateway/wiring.py and callers | registry/model_registry.py | Weak (whole-file rewrite, no lock) | Durable, single host | Manual (whole-file restore) | Yes, low write frequency makes this tractable |
| Deployment registry (Gateway worker registry) | JSON files, one per worker (SOVEREIGN); not yet distributed | gateway.py's routing | gateway/worker.py's save()/load() | Weak (no lock, no atomic rename -- disclosed real gap) | Durable, single host | Manual; a concurrent-write corruption is possible and undetected today | Yes, recommended given the weak-consistency gap |
| Dataset registry | JSON-per-artifact (SOVEREIGN) | training pipeline (out-of-band) | registry/dataset_manifest.py | Weak | Durable, single host | Manual | Yes |
| Training registry | JSON-per-run (SOVEREIGN) | learning pipeline (out-of-band, never the hot request path) | registry/training_run.py | Weak | Durable, single host | Manual | Yes, lower priority (reconstructable from training logs) |
| Memory stores (episodic/semantic) | JSON/JSONL files (SOVEREIGN); not yet distributed | brain/memory.py, memory/store.py callers | memory/episodic.py, memory/store.py | Weak (check-then-act race on episodic idempotency check -- disclosed real gap) | Durable, single host | Manual | Yes, user-facing data -- recommend prioritizing distribution of this store next after Godmode |
| Connector state/policies | In-memory dicts, PROCESS_LOCAL | connectors/registry.py, lifecycle.py callers | same | n/a (rebuilt on every process start from static policy + live provider calls) | None (by design -- see connectors/lifecycle.py's own docstring: "request-driven, bounded, no background sync engine required") | Rebuild on restart | No -- REBUILDABLE_CACHE |
| WorldState (Cognitive Court) | Request-scoped dataclass, PROCESS_LOCAL, by design | deliberation/* within one request | same | n/a | None | n/a | No |
| Audit events | In-memory list (`_AUDIT_LOG`, Godmode); hash-chained table (`audit_log`, auth DB, SQLite or Postgres) | audit review tooling | audit.py, godmode/audit.py | Godmode: none (in-memory only, not yet shared across processes); auth audit: strict, hash-chained, append-only (DB trigger/rule enforced) | Godmode audit: none, real gap; auth audit: durable | Auth audit: DB backup/restore; Godmode audit: none possible today | Auth audit: yes (compliance-relevant); Godmode: not yet backed by durable storage -- disclosed gap |
| Simulation records | Not persisted, by design (pure preview path) | n/a | n/a | n/a | None | n/a | No |
| Auth/session/API-key/org state | SQLite (SOVEREIGN) or PostgreSQL (DISTRIBUTED) | auth/store.py, apikeys.py, org_store.py | same | Strict (transactional) | Durable | `orca/ops/backup.py`'s `restore_sqlite()`/documented `pg_restore` path | Yes -- already has a real backup tool (predates this phase) |
| Chat sessions (`_sessions`) | In-process dict (SOVEREIGN) or Redis (DISTRIBUTED, opt-in) | serve/api.py's `_Session` | same | SOVEREIGN: none (disclosed real gap); DISTRIBUTED: Redis's own atomicity, proven this phase via real multiprocess test | SOVEREIGN: none; DISTRIBUTED: durable per Redis's own persistence config | Redis's own (RDB/AOF, outside this codebase's control) | Recommend Redis persistence config as an operational requirement for DISTRIBUTED, not covered by ORNEUR's own backup tooling |
| Rate-limit counters | In-process dict (SOVEREIGN) or Redis (DISTRIBUTED, opt-in) | serve/ratelimit.py | same | SOVEREIGN: `threading.Lock`, single-process; DISTRIBUTED: Redis atomic ops | Ephemeral by design (counters reset naturally) | n/a | No -- REBUILDABLE_CACHE |
| DocStore | ChromaDB (SOVEREIGN); not yet distributed | docs/store.py callers | same | ChromaDB-internal | Durable, single host | Manual (ChromaDB's own persistence dir) | Yes, user-facing data |

## Phase 14A.4 addendum — `ORNEUR_DATABASE_URL` full audit (spec §2)

Exactly what this one connection string owns, per-table (confirmed by
reading `orca/auth/db.py`'s schema constants directly, and asserted as
a living contract in
`tests/test_distributed_core_db_config_gate.py::test_auth_db_owns_the_expected_tables`):

| State | Owner | Backend | Readers | Writers | Consistency requirement | Distributed required | Fallback behavior |
|---|---|---|---|---|---|---|---|
| `users` | `orca/auth/db.py` | SQLite/Postgres via `ORNEUR_DATABASE_URL` | `auth/store.py`, `auth/routes.py` | `auth/store.py`'s `create_user`/`update_password`/etc. | Strict (unique email constraint, transactional) | **YES** — two hosts with independent SQLite files would allow duplicate accounts / diverging credentials | **CLOSED this phase** — DISTRIBUTED without a valid URL now fails startup |
| `signup_counter` | same | same | `auth/store.py::create_user` | same | Strict (atomic `UPDATE...RETURNING`, explicitly designed for concurrent-safe sequencing) | **YES** — the entire reason this is a dedicated counter, not `COUNT(*)`, is cross-process/cross-host race-safety | **CLOSED this phase** |
| `usage_daily` | same | same | `auth/store.py::check_quota` | `increment_usage` | Strict-ish (a lost update here under-counts a quota, not a security event) | **YES** for correctness of quota enforcement across workers | **CLOSED this phase** |
| `user_sessions` | same | same | `auth/store.py::get_user_session_ids` | `record_user_session` | Eventually-consistent acceptable (a listing endpoint, not an auth decision) | **YES** for cross-worker session visibility (proven this phase, real two-process test) | **CLOSED this phase** |
| `organizations` / `org_members` | same | same | `auth/org_store.py` | same | Strict (seat-limit enforcement, invite tokens) | **YES** — seat limits and invite state must not diverge per host | **CLOSED this phase** |
| `privacy_consents` / `consent_audit_log` | same | same | `auth/privacy.py` | same | Strict; `consent_audit_log` is append-only (DB-trigger/rule enforced, not just convention) | **YES** — compliance-relevant, must not diverge or be locally overwritable | **CLOSED this phase** |
| `data_export_requests` | same | same | `auth/privacy.py` | same | Strict (one pending request per user, enforced at the row level) | **YES** | **CLOSED this phase** |
| `security_breach_log` | same | same | `auth/privacy.py` | same | Strict, immutable (DELETE blocked at the DB layer) | **YES** — an incident record diverging per host defeats its purpose | **CLOSED this phase** |
| `audit_log` (hash-chained) | `orca/audit.py`, using `get_conn()`/`BACKEND` from `auth/db.py` | same | `orca/audit.py::recent`/`verify_chain`/`export_for_audit` | `orca/audit.py::log()` | Strict — Postgres path uses `pg_advisory_xact_lock` specifically because "multiple API instances writing to the same database" was already an anticipated case; the hash chain itself would visibly break if two hosts each maintained independent chains | **YES** | **CLOSED this phase** — same URL, same enforcement |
| Godmode elevation audit (`orca/godmode/audit.py`) | **NOT** `ORNEUR_DATABASE_URL` — a separate, pre-existing, in-memory-only mechanism | n/a | simulation/eval tooling only | `record_elevation_event()` | None — plain Python list, never persisted, never shared across processes | Not applicable to this phase's scope (a genuinely separate mechanism) | **NOT CLOSED, pre-existing, disclosed** — see "Audit durability" below |

### Audit durability (spec §14) — inspected, not redesigned

`orca/godmode/audit.py`'s elevation audit trail is a plain in-memory
list (`_AUDIT_LOG`), completely separate from `ORNEUR_DATABASE_URL`'s
hash-chained `audit_log` table. Confirmed directly (and asserted as a
living contract,
`test_godmode_elevation_audit_is_in_memory_only_and_does_not_gate_authorization`):
`orca/godmode/resolution.py`'s authorization decision does **not** call
or depend on either audit mechanism succeeding — there is no "durable
audit required before authorization" architecture in this codebase for
this phase to have silently violated. This is the same real, pre-
existing gap `STATE_OWNERSHIP.md`'s original Phase 14A audit already
disclosed ("Godmode audit: none, real gap") — not newly introduced,
not made worse, and not silently hidden behind this phase's core-DB
enforcement work. `orca.audit.log()` itself (the ORNEUR_DATABASE_URL-
backed, hash-chained mechanism used for auth/session events) has its
own explicit, documented, pre-existing fail-soft contract — "Never
raises... Returns the entry id, or None on failure" — confirmed
directly against a broken backend
(`test_orca_audit_log_never_raises_and_reports_failure_via_none_return`).
This is intentional (audit failures must not break the request being
logged) and was not changed this phase.

## Ownership principle applied

Every row above that says "not yet distributed" or "disclosed real
gap" is being reported honestly rather than silently upgraded to look
solved — this table exists specifically so a reader can tell, at a
glance, which parts of ORNEUR DISTRIBUTED are load-bearing-tested this
phase (Godmode leases, chat sessions via Redis) versus which remain
exactly as single-host-shaped as `CURRENT_DEPLOYMENT_ARCHITECTURE.md`
found them.
