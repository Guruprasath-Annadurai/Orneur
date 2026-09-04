# Phase 14 §6 — Formal State Ownership Catalog

This formalizes `CURRENT_DEPLOYMENT_ARCHITECTURE.md`'s audit into the
owner/readers/writers/consistency/persistence/recovery/backup shape the
spec requires, for every state category §6 names explicitly.

| State | Owner (backend) | Readers | Writers | Consistency | Persistence | Recovery | Backup requirement |
|---|---|---|---|---|---|---|---|
| Godmode leases | SQLite (SOVEREIGN) or PostgreSQL (DISTRIBUTED) | resolution.py, connector_elevation.py, delegation.py | issuance.py, lease_store.py's consume_use/revoke/reserve_uses | Strict (transactional, `BEGIN IMMEDIATE` or `SELECT...FOR UPDATE`) | Durable | Reconciled via `revocation_ledger.py` after any restore -- **mandatory**, see `BACKUP_AND_RECOVERY.md` | Yes -- critical, sensitive (contains capability grants) |
| Kill switch | Same authority database as leases (SQLite table for SOVEREIGN, Postgres table for DISTRIBUTED) as of Phase 14A.1 | resolution.py, connector_elevation.py | godmode/kill_switch.py's activate/deactivate (via lease_store's ks_get_state/ks_set_state) | Strict (transactional), cross-worker-visible in DISTRIBUTED | Durable | Reconciled via `kill_switch_ledger.py`'s `reconcile_after_restore()` -- **mandatory**, see `KILL_SWITCH_DURABILITY.md` | Yes -- same criticality as leases; the separate append-only ledger must be backed up independently of the state table itself |
| Kill-switch event ledger | Append-only JSONL file, deliberately independent of the kill_switch_state table's backup unit | `kill_switch_ledger.py`'s `reconcile_after_restore()` | `kill_switch.activate()`/`deactivate()` | Append-only, eventually-consistent is fine | Durable, ideally on independently-backed-up storage | This IS the recovery mechanism for kill-switch state | Yes -- same criticality as the revocation ledger |
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

## Ownership principle applied

Every row above that says "not yet distributed" or "disclosed real
gap" is being reported honestly rather than silently upgraded to look
solved — this table exists specifically so a reader can tell, at a
glance, which parts of ORNEUR DISTRIBUTED are load-bearing-tested this
phase (Godmode leases, chat sessions via Redis) versus which remain
exactly as single-host-shaped as `CURRENT_DEPLOYMENT_ARCHITECTURE.md`
found them.
