# Phase 14 — Current Deployment Architecture Audit

## Method

This audit inspects the real code as it exists today (branch
`session-update-2026-08-25`, commit `9a453d595d07144dffc9d4773e3e484e9641bf0e`)
for single-host assumptions, before any Phase 14 distributed work begins.
Every claim below cites a file and line. This is a factual snapshot, not
a target architecture (that is `ARCHITECTURE.md`, §3 of the governing
spec).

## Global pattern

`orca/config.py:49-59` resolves `ORCA_HOME` to `~/.orca` by default
(overridable via `ORNEUR_HOME`/`ORCA_HOME`). The overwhelming majority of
subsystems below default to a file or directory under this single local
path. **This is the central finding**: today, ORNEUR assumes one
machine, one `ORCA_HOME`, one process (or at most several processes on
that one host, as Phase 13 proved safe for Godmode specifically).

Today's actual serving topology is a **single uvicorn process**
(`orca/cli.py:1550`, no `workers=` argument) with `replicas: 1` in the
existing `k8s/deployment.yaml:8`. There is no multi-worker API today.

## State classification

| Subsystem | State | Location | Classification | Lock/transaction |
|---|---|---|---|---|
| Chat sessions | `_sessions: dict` | `orca/serve/api.py:393` | **PROCESS_LOCAL** | none — a real gap, called out by `session_store.py`'s own docstring |
| Daily escalation cap | `_escalations_by_day: dict` | `orca/serve/routing.py:49` | **PROCESS_LOCAL** | none (race under concurrency) |
| Ollama tag cache | `_tags_cache` | `orca/serve/registry.py:46` | **REBUILDABLE_CACHE** | none needed (rebuildable) |
| Rate-limit counters | `_local_counters` | `orca/serve/ratelimit.py:32-33` | **HOST_LOCAL** (opt-in **DISTRIBUTED_REQUIRED** via Redis) | `threading.Lock` locally; Redis when `ORCA_REDIS_URL` set |
| Cross-instance sessions | Redis-backed store | `orca/serve/session_store.py` | **DISTRIBUTED_REQUIRED**, opt-in | Redis is externally atomic |
| Gateway worker registry | JSON file per worker | `orca/gateway/worker.py:19,57-68,96` | **SHARED_HOST** (file-based, not lock-protected) | **none** — real gap: no locking or atomic rename |
| Gateway routing tables | `_runtimes/_deployments/_workers` dicts | `orca/gateway/gateway.py:74-76` | **PROCESS_LOCAL** | none (rebuilt on startup) |
| Circuit breaker state | `_breakers: dict` | `orca/gateway/circuit_breaker.py:29-31` | **PROCESS_LOCAL** | none (single-threaded asyncio assumption) |
| Concurrency limiter / queue | `_waiters: list` | `orca/gateway/concurrency.py:66-75` | **PROCESS_LOCAL** | `asyncio.Lock` |
| Cognitive Kernel state | request-scoped dataclasses | `orca/cognitive/contracts.py` | **PROCESS_LOCAL** (by design — never persisted) | n/a |
| Truth Fabric evidence graph | `EvidenceGraph._nodes/_edges` | `orca/truth/graph.py:16-18` | **PROCESS_LOCAL** (by design) | n/a |
| Episodic memory | JSONL ledger per scope | `orca/memory/episodic.py:32,34,42` | **SHARED_HOST** (file-based) | **none** — check-then-act race on the idempotency check |
| Semantic memory | JSON file per record | `orca/memory/store.py:36,46,71` | **SHARED_HOST** (file-based) | none |
| Legacy brain memory | in-process + ChromaDB | `orca/brain/memory.py:20,41` | short-term: **PROCESS_LOCAL**; long-term: **SHARED_HOST** | n/a |
| Cognitive Court WorldState | request-scoped dataclass | `orca/deliberation/contracts.py:177` | **PROCESS_LOCAL** (by design, explicit docstring) | n/a |
| Model Society budget ledger | per-invocation dataclass | `orca/society/budget_ledger.py:121-135` | **PROCESS_LOCAL** (by design) | n/a |
| Agent Runtime cognitive budget | fields on `CognitiveBudget`, threaded via `DelegationRequest` | `orca/agent/contracts.py:279-296`, `orca/agent/delegation.py:68-70` | **PROCESS_LOCAL**, request-scoped object — never a shared/global counter | n/a |
| Connector registry / health | `_instances/_health` dicts | `orca/connectors/registry.py:29-40` | **PROCESS_LOCAL** | none |
| Connector sync state / revocation tracker | dicts | `orca/connectors/lifecycle.py:12-45` | **PROCESS_LOCAL** | none |
| Godmode leases | SQLite, `BEGIN IMMEDIATE` | `orca/godmode/lease_store.py:103,184,222,288,364` | **HOST_LOCAL authoritative** (SQLite file locking is single-host only) | yes — proven cross-process, single-host (Phase 13.2/13.3) |
| Godmode kill switch | file-existence flag | `orca/godmode/kill_switch.py:20,29,41` | **HOST_LOCAL authoritative** | atomic at OS level (existence check), single-host only |
| Simulation Chamber results | returned dataclasses, never persisted | `orca/simulation/chamber.py` | **PROCESS_LOCAL** (by design — pure preview path) | n/a |
| Learning/training pipeline | CLI/cron-invoked, separate process | `orca/learning/pipeline.py:6` | **EXTERNAL_SERVICE**-equivalent (out-of-band, never in the request path) | n/a |
| Model registry | single JSON file, whole-file rewrite | `orca/registry/model_registry.py:25,54` | **SHARED_HOST** (file-based) | **none** — write-whole-file-on-save, no atomic rename |
| Checkpoint / dataset manifest / evaluation / training-run registries | JSON-per-artifact | `orca/registry/checkpoint.py:20`, `dataset_manifest.py:21`, `evaluation_registry.py:22`, `training_run.py:17` | **IMMUTABLE_ARTIFACT** (checkpoints/datasets themselves) + **SHARED_HOST** (their metadata index) | none |
| Auth store | SQLite by default, Postgres when `ORCA_DATABASE_URL` set | `orca/auth/db.py:28-30` | **HOST_LOCAL** by default, **DISTRIBUTED_REQUIRED**-capable (Postgres) | yes, either backend — the one subsystem already designed for multi-host |
| Backups | cron/manually invoked, `Connection.backup()`/`pg_dump` | `orca/ops/backup.py:5-13,34` | **EXTERNAL_SERVICE**-equivalent (out-of-band) | n/a |
| DocStore | ChromaDB, one collection per session | `orca/docs/store.py:27,107` | **SHARED_HOST** | ChromaDB-internal |
| Lens job queue | file-backed | `orca/lens/queue.py:42` | **SHARED_HOST** | **none** |
| Governance model cards | JSON-per-card | `orca/governance/model_cards.py:37` | **SHARED_HOST** | none |
| License state | single JSON file | `orca/license/store.py:34` | **SHARED_HOST** | none |

## Health endpoints

Only `/healthz` exists (`orca/serve/api.py:502`), used for **both**
`livenessProbe` and `readinessProbe` in the existing
`k8s/deployment.yaml:65-73`. **Liveness and readiness are conflated
today** — this is a real gap Phase 14 must close (see
`HEALTH_AND_READINESS.md`).

## Queue / backpressure inventory

Real backpressure exists only in `orca/gateway/concurrency.py`
(`asyncio.Lock`-protected, priority+aging queue) and
`orca/gateway/circuit_breaker.py` — both **process-local**. No
cross-process or cross-host accounting exists anywhere today.

## Bottom line

Only two subsystems have any built-in multi-host awareness today:
`orca/auth/db.py` (Postgres option) and
`orca/serve/session_store.py` / `ratelimit.py` (Redis option, both
opt-in via environment variables). Everything else — the gateway worker
registry, memory, all of `orca/registry/`, connectors, the lens queue,
model cards, license state — assumes one shared `ORCA_HOME` filesystem
and effectively no file locking beyond Godmode's SQLite `BEGIN
IMMEDIATE` transactions (which are themselves proven single-host only).

This audit directly motivates Phase 14 §4-6's requirement: **Godmode's
SQLite store cannot be replicated per-host if Phase 14 introduces
multiple hosts** — see `AUTHORITY_DISTRIBUTION.md` for the chosen
architecture.
