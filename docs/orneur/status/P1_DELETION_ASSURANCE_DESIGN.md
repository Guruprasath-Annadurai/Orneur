# Priority 1 — Complete Deletion Assurance: Design & Adversarial Evidence

Status date: 2026-10-15. Scope: `LongTermMemory` (ChromaDB-backed vector
store) deletion, per the POST-AUDIT #012 directive's Priority 1. This
document is the evidence record `orca/brain/memory.py`'s docstrings point
to. It is deliberately specific about what was tested, what the result
was, and which design choices follow directly from that evidence rather
than from assumption.

## 1. The seven guarantees, current state

| # | Guarantee | Status |
|---|---|---|
| 1 | Logical deletion / retrieval prevention | **Done.** `delete_collection()` removes the collection from every normal chromadb query path; verified by `recall()` returning `[]` immediately after, in every test and every manual reproduction below. |
| 2 | Active-database page reclamation | **Done, best-effort.** `VACUUM` physically rewrites the shared `chroma.sqlite3` file. Bounded to `_RECLAIM_TIMEOUT_S` (2s); success is `RECLAIMED`, bounded-timeout failure is `DEFERRED` and durably recorded for retry (§4). |
| 3 | VACUUM failure/timeout | **Done.** See `DEFERRED` + `pending_reclamation.json` ledger, self-healing on any later successful VACUUM (one VACUUM rebuilds the whole shared file, clearing every session's pending entry, not just the one that triggered it). |
| 4 | Concurrent reads/writes across separate worker *processes* | **Tested extensively, bounded with a disclosed limitation.** See §2 and §3. |
| 5 | Crash/restart recovery | **Tested, confirmed safe.** See §3. |
| 6 | Backups/snapshots/retention | **Not applicable to this codebase** — see §6. |
| 7 | User-visible deletion status | **Done.** `DeletionResult(logical_deleted, physical_reclamation)` — see `account_delete.py`'s split response fields. |

## 2. Multi-process contention — what was actually tested

All of the following were reproduced with genuine separate OS processes
(`subprocess.Popen`), not same-process threads, because same-process
threading does not represent real multi-worker-process deployment
concurrency honestly.

- **3 concurrent tight-loop writer processes** against the shared
  `chroma.sqlite3`: 0 errors.
- **2 simultaneous cross-process `delete()` calls**: both completed
  cleanly.
- **A deliberately-held `BEGIN IMMEDIATE` write lock** from a separate
  process, held for 15s and separately for 30s: `delete()` (pre-fix,
  unbounded `sqlite3.connect(timeout=...)`) blocked for the *entire*
  duration of the competing hold (29.09s measured against a 30s hold) —
  confirmed availability risk, not a corruption risk. This is the
  regression `_RECLAIM_TIMEOUT_S` / `_DELETE_REQUEST_BUDGET_S` exist to
  bound.

Conclusion from this section alone: SQLite's own file locking and
busy-wait retry behave correctly under concurrent writes/deletes across
real separate processes. The only confirmed problem is *how long* a
request can be made to wait by an unrelated process's held lock, not data
safety.

## 3. Crash recovery — `kill -9` mid-VACUUM

Reproduced directly (background task `bt9khjj1n`): a VACUUM was started
against the shared file, then the process executing it was sent `kill -9`
mid-operation. Result:

```
killed process output:
exit code: -9
integrity_check after kill -9 mid-delete: [('ok',)]
B data still queryable after crash: [... 3 records, all intact ...]
```

`PRAGMA integrity_check` returned clean (`ok`), and a second, unrelated
session's data (`B`) remained fully present and queryable immediately
afterward — no hang, no corruption, no failed subsequent connection.
SQLite's journal-based crash recovery handled this correctly. This
specific result is genuine and was used, correctly, to justify one design
decision: that **forcibly killing a process mid-VACUUM/mid-delete does
not corrupt the shared store or leave it in a state that blocks other
sessions.**

**What this result does NOT establish**, and which a later part of this
work initially over-extended it to justify (see §4): it says nothing
about whether a *different, freshly-started* process's chromadb client
can reliably *see* collections created by another process's client. Crash
safety at the SQLite-file level and client-side collection-catalog
visibility are two independent properties; this test only speaks to the
first.

## 4. The timeout-enforcement mechanism — two attempts, one rejected

### Attempt A: `concurrent.futures.ThreadPoolExecutor` + `Future.result(timeout=...)`

The straightforward application-level bound: run `_delete_sync()` in a
single dedicated worker thread, wait on `future.result(timeout=5.0)`.

**Found broken (not merely imprecise) under real contention**: against a
genuinely held SQLite lock (separate process, `BEGIN IMMEDIATE`, held
15s), this measured **~13.87–13.89s** before `TimeoutError` was raised,
despite the 5.0s budget — confirmed in three independent reproductions
(via `delete()`, via `delete_session()`, and via directly calling
`_delete_executor.submit(...)` + `future.result(timeout=5.0)` in
isolation). A sanity check on the *same executor* with a plain
`time.sleep(20)` task correctly timed out at exactly its requested 3.0s,
ruling out a logic bug on our side. Conclusion: a thread blocked inside a
native chromadb/sqlite3 call does not cooperate with Python's
GIL/threading timeout machinery the way pure-Python code does — the
bound is real for ordinary contention, but not reliable under extreme
contention.

This is a **disclosed, accepted limitation** of the implementation that
shipped (see §5), not a silent one: `PENDING`'s docstring in
`orca/brain/memory.py` states plainly that wall-clock latency before
`PENDING` is reported is not as tightly bounded as the configured budget
implies under pathological contention.

### Attempt B: `multiprocessing.Process` + `Process.join(timeout=...)` + `terminate()`/`kill()`

Motivated directly by §3's crash-safety result: since a genuinely separate
OS process *can* be forcibly killed (unlike a thread stuck in a
non-cooperative native call), and since killing mid-operation was already
confirmed not to corrupt the shared store, this seemed like a strictly
better mechanism — a real, OS-enforced hard timeout instead of Attempt
A's cooperative one.

**Implemented, then rejected** after its own adversarial test (not an
assumption) found a new, more serious failure mode:

- A `chromadb.PersistentClient` constructed in a **brand-new OS process**,
  immediately after a *different* process's client created and populated
  a collection, raised `chromadb.errors.NotFoundError` on
  `delete_collection()` for that collection — even though the creating
  process's `store()` call had already returned successfully, and even
  though the underlying SQLite file was confirmed fully durable and
  intact at that point (ruling out a storage-durability explanation; this
  is chromadb's own client-side collection cache/catalog).
- This was **not a brief, bounded catch-up delay**. A bounded retry loop
  (up to ~3.5s, with backoff) did not reliably resolve it under the load
  generated by this file's own full test suite running multiple deletions
  against the same shared store in sequence.
- Critically: when the "exhausted retries ⇒ treat as already deleted"
  shortcut was tried as a fix, it produced a confirmed **false positive**:
  `delete_session()` reported `logical_deleted=True`, while a fresh client
  back in the *original* process could still `recall()` the same data
  immediately afterward. That is exactly the kind of invented, unearned
  guarantee this whole effort exists to avoid — and a strictly **worse**
  failure mode than Attempt A's merely-slow-but-honest `PENDING`: Attempt
  A never lies about an outcome, it only sometimes takes longer than its
  nominal budget to report one.

**Decision: Attempt B was reverted.** Attempt A (thread-based, with its
disclosed latency-bound limitation) is what shipped. This is recorded here
specifically so a future pass does not re-attempt the multiprocessing
redesign without first re-deriving why it was rejected — the crash-safety
result from §3 is real and does justify killing a process as *safe*, but
it does not make a freshly-started process's chromadb client a *reliable*
substitute for a thread that shares its process's already-warm, consistent
view of the collection catalog.

## 5. What actually shipped

- `DeletionResult(logical_deleted: bool, physical_reclamation: str)` —
  logical success (the real privacy guarantee) reported separately from
  best-effort physical byte-reclamation, never conflated.
- `LongTermMemory.delete_session(session_id)` classmethod: does not
  require a pre-constructed instance, so nothing related to deletion
  (including chromadb client construction) can block the calling thread
  before the bounded worker thread starts.
- Bounded via `concurrent.futures.ThreadPoolExecutor(max_workers=1)` +
  `future.result(timeout=_DELETE_REQUEST_BUDGET_S)` (Attempt A, §4).
  `TimeoutError` → `PENDING`, with the real outcome recorded durably via a
  `done_callback` once the background attempt actually finishes (it is
  never cancelled — a thread blocked in a native call cannot be safely
  killed from pure Python, and §4 explains why killing the *process*
  instead was tried and rejected).
- `_vacuum_shared_file()`: explicit `_RECLAIM_TIMEOUT_S`-bounded VACUUM.
  `DEFERRED` on timeout, durably ledgered in `pending_reclamation.json`,
  self-healing on any later successful VACUUM.
- `pending_logical_deletion.json`: durable ledger for the rarer `PENDING`
  case, resolved by `check_pending_logical_deletions()`.
- `account_delete.py` reports `long_term_vector_memory_logically_deleted`
  and `long_term_vector_memory_physical_reclamation` as separate fields —
  no caller collapses them back into one boolean.

## 6. Backups/snapshots/retention (guarantee #6)

This codebase has no backup/snapshot infrastructure for the vector store
— there is nothing to evaluate empirically here, and inventing a
retention guarantee for infrastructure that does not exist would violate
the directive's explicit instruction not to invent guarantees the
filesystem/SQLite/backups cannot provide. Documented as: **if an operator
adds file-level backups of `MEMORY_DIR/vectors/` in the future, a
`delete_session()` call does not and cannot retroactively purge a
session's data from an already-taken backup snapshot** — that is a
backup-retention-policy question for whoever owns that infrastructure,
not something this module can satisfy.

## 7. Alternatives considered and not chosen (for this pass)

- **Database-level locking changes** (e.g. switching SQLite to WAL mode
  explicitly, or a different busy-timeout strategy): would not change the
  fundamental finding in §4 — the problem is a non-cooperative native call
  not yielding to a timeout, not a lock-wait-strategy misconfiguration.
- **Dedicated cleanup-worker process/queue**: adds real operational
  infrastructure (a queue, a worker deployment) for a problem the existing
  ledger + opportunistic self-healing retry already solves at zero
  infrastructure cost for the realistic contention levels measured in §2.
  Worth revisiting if production contention is ever measured to be worse
  than what was reproduced here.
- **Per-session storage isolation** (one SQLite file per session instead
  of one shared file): would eliminate cross-session VACUUM blocking
  entirely, at the cost of a much larger structural change (file-per-
  session fan-out, migration of the existing shared store). Flagged as
  the strongest structural fix if contention in production ever exceeds
  what the current bounded-wait design tolerates.
- **Encryption-key lifecycle / crypto-shredding** (encrypt each session's
  vectors under a per-session key, delete the key instead of the data):
  the strongest possible guarantee — reclamation becomes instant and
  independent of VACUUM/contention entirely — but is a materially larger
  change (key management, per-session encryption at the embedding-store
  layer) out of scope for this bounded pass. Recommended as the long-term
  direction if guarantee #2/#3 ever need to be stronger than best-effort.

## 8. Architecture decision review (CTO directive, 2026-10-15)

Triggered by Decision: OPTION B — continue bounded architecture
investigation rather than accept the thread-based timing limitation
silently. This section evaluates the three requested options and gives a
definitive, scope-bounded recommendation grounded in a fact checked
directly against the installed chromadb (1.5.9) source, not assumed:

> `chromadb.PersistentClient`'s own docstring: *"This client is intended
> for local development and testing. For production, prefer a
> server-backed Chroma instance."*

And a fact checked against this codebase's actual deployment entrypoint
(`orca/cli.py`'s `serve` command): `uvicorn.run(create_app(), ...)` is
called with **no `workers=` argument** — this codebase runs today as a
**single process**. The multi-worker-process topology Audit #012 already
scoped as *not yet accepted* ("accepts the tested remediation scope only,
not ... multi-worker deployment") is not how `orca` is actually deployed
right now. This matters directly: it changes which of chromadb's own
documented constraints are a live production risk versus a forward-looking
one, and is why the recommendation below is scope-bounded rather than a
single blanket verdict.

### 8.1 Option evaluation

| Criterion | 1. Tombstones + async reclamation (what shipped, §5) | 2. Single-writer / dedicated maintenance ownership | 3. Per-session isolation + crypto-shredding |
|---|---|---|---|
| Correctness across multiple processes | **Correct for 1 process** (the actual current deployment). **Not applicable/unsound for >1 process** — same chromadb embedded-mode limitation found in §4 Attempt B applies to ANY code that opens a fresh `PersistentClient` in a second process, not just a deletion worker. | **Correct by construction** — exactly chromadb's own recommended shape: one process (a `chroma run` server, or an in-process server component) owns the store; every other process is a thin client over a network interface with no local-file race at all. | **Correct**, and strictly stronger for reclamation (key destruction is independent of VACUUM/contention entirely) — but does not by itself solve chromadb's embedded-mode multi-process issue unless paired with option 2 (one owner per shard). |
| Immediate revocation of logical access | Yes — `delete_collection()` removes it from every query path immediately, same process. | Yes — same guarantee, routed through the owning server. | Yes, and additionally: even raw-byte recovery is cut off the instant the key is destroyed, independent of VACUUM. |
| Crash and restart recovery | **Tested, confirmed safe** (§3). | Confirmed-safe SQLite semantics still apply underneath; adds a new failure mode to design for: the owning server process itself crashing (needs its own restart/health-check story). | Same SQLite crash-safety, plus key-store crash-safety becomes a new dependency to get right. |
| Bounded user-facing latency | **Disclosed limitation**: cooperative thread timeout, not OS-enforced (§4 Attempt A). | Can be tightly bounded — a single owner with a real network RPC timeout is a normal, well-understood bound (unlike a blocked native call in-process). | Bounded — key destruction is a fast, independent operation; physical-byte cleanup can remain best-effort/async as today. |
| Durable cleanup retries | **Done** — ledgers in §3/§5. | Same ledger design still applies, now owned by the single-writer service. | Simpler: "has the key been destroyed" durably replaces "has VACUUM run" as the retry subject. |
| Raw-byte / backup retention guarantees | Best-effort VACUUM only; no stronger guarantee possible against an already-taken backup (§6). | Same ceiling — a single writer does not change what VACUUM or a backup snapshot can guarantee. | **Strictly stronger**: a backup snapshot taken before key destruction becomes cryptographically inert after destruction, which VACUUM-based approaches cannot offer at all. |
| Tenant isolation | Shared file; isolation is logical only (collection naming), not physical. | Unchanged by itself — isolation is orthogonal to who owns the writer. | **Strictly stronger** if paired with per-tenant storage partitioning, not just per-tenant keys. |
| Operational complexity / cost | **Zero new infrastructure** — what's already running. | New: a service to deploy, monitor, and keep available (a single point of failure for all memory reads/writes unless made HA, which is further complexity). | New: a key-management component (generation, storage, destruction, backup of the key store itself — which must NOT be backed up alongside the data it protects, or shredding is defeated). |
| Compatibility with existing ORNEUR architecture | **Full** — no call-site changes beyond what already shipped. | Requires migrating every chromadb call site (store/recall/delete), not just deletion, to a client/server split — a whole-subsystem change. | Requires a new encryption layer between `LongTermMemory` and chromadb for every write, not just delete — also a whole-subsystem change. |

### 8.2 (superseded by §8.3 — kept for the record)

An earlier pass of this review concluded the multi-worker-process question
was purely forward-looking and out of current scope, based on
`replicas: 1` and no `workers=` argument on `uvicorn.run(...)`. That
conclusion was **corrected** after further investigation (§8.3): a
genuinely separate, already-shipped OS process (`orca/mcp/memory_server.py`)
accesses the same shared store today, so this is a **live, existing**
exposure, not only a future one. The reasoning here is kept, struck
through in spirit, because the option-evaluation table in §8.1 and most
of its content still stand — only the scoping conclusion changes.

### 8.3 CORRECTION — this is an existing exposure, not only a future one

Directive correction (2026-10-15): `orca/mcp/memory_server.py` is a
**genuinely independent, already-shipped OS process** (a stdio MCP server
for IDE integrations, started with `python -m orca.mcp.memory_server` or
equivalent, entirely separate from `orca serve`'s uvicorn process) that
constructs its own `MemoryEngine`/`LongTermMemory` against the exact same
`MEMORY_DIR/vectors`. Nothing prevents a developer or deployment from
running both at once today. This invalidates treating "multi-process" as
a purely future, opt-in concern — it is a **present, unenforced**
architectural risk. Three things were directly tested as a result:

**1. Deployment-scope audit (directive requirement #1).** Every entry
point that can touch this store was enumerated and checked, not assumed:
`orca serve` (uvicorn, single process, confirmed), `orca/mcp/memory_server.py`
(separate process, confirmed, no coordination), CLI/TUI (confirmed: only
touch `EpisodicMemory`, a plain JSON file — no chromadb exposure), `orca/docs/store.py`
(its own independent `PersistentClient`, but against a **different**
directory, `ORCA_HOME/docs/vectors` — confirmed no overlap with this
store, though it carries the identical architectural risk class
independently). `k8s/deployment.yaml`: `replicas: 1` for the API
deployment, `ORCA_HOME` mounted from a PersistentVolumeClaim
(`orneur-api-pvc`) — a one-line replica-count change would let multiple
pods share that exact volume, with no application-level guard against it.
**Single-writer ownership is not enforced anywhere in this codebase** —
grepped for `flock`/`fcntl`/pidfile/singleton patterns near the vectors
path and found none. It is a deployment convention, not an invariant the
code checks.

**2. Direct reproduction of real, overlapping API-process vs.
MCP-process-shaped access** (not sequential, not simulated — genuine
concurrent `subprocess`/`multiprocessing` processes against a real shared
store with 30 preloaded collections, matching the load level under which
the original NotFoundError race was observed): a writer process
`store()`-ing a fact while a second, independent process concurrently
`recall()`s the same session measured a **~40–45% silent miss rate**
across two independent 15-trial runs (6/15 and 7/15 misses) — the reader
gets back an empty result, no exception, with the data fully present and
durable the whole time.

**3. An advisory cross-process `flock`, wrapping every chromadb client
construction/operation in both processes, was tried as the obvious
in-scope coordination fix and did NOT resolve it** — re-running the exact
same test with serialized access still measured 7/15 misses. This is
conclusive evidence (not a guess) that the problem is not raw-file-access
interleaving (which a lock would fix) but chromadb's own client-side
catalog/segment caching not reflecting another process's recent commits
even when access is serialized. **A simple application-level coordination
mechanism is not a safe fix.**

**4. A new, more severe failure mode surfaced while building the
regression test for finding #2**: a genuine concurrent read against a
collection still mid-write can raise `chromadb.errors.InternalError:
Error executing plan: Internal error: Error creating hnsw segment reader:
Nothing found on disk` — a real exception a live API/MCP request would
have to handle, not just a silent empty result. Worse: **once this
happens, the SAME process's chromadb client remains unable to read that
collection for the rest of that process's lifetime, even via a brand-new
`LongTermMemory` instance** — a persistent, in-process cache-poisoning
effect from one bad concurrent access, confirmed by reproduction
(`tests/test_memory_long_term_chroma_privacy.py::test_concurrent_real_processes_can_silently_miss_a_just_written_fact`).
Verified via a genuinely independent third process (never party to the
race) that the underlying data itself is NOT lost — this is a client-side
cache-poisoning bug, not on-disk data loss — but a live API or MCP process
that experiences this would need a restart to recover read access to that
collection, which is a real availability and correctness problem for the
deployment as it exists today.

**Corrected recommendation**: given direct, tested evidence that (a) this
is a present, not merely future, exposure, and (b) the obvious in-scope
coordination fix (an advisory lock) does not resolve it, **a safe,
enforced single-owner mechanism is not demonstrably feasible within this
PR's scope.** The only architecturally sound fix remains Option 2
(chromadb's own client-server mode, §8.1), which requires migrating every
chromadb call site — not just deletion — and standing up new operational
infrastructure. That is a distinct, resourced architectural decision for
an operator to make, not something this PR can respond to with a quick
patch. **This PR does not claim the broader API/MCP concurrent-access
question is resolved.** What it does claim, narrowly and correctly: the
deletion-assurance design in §5 is correct for a **single chromadb client
process at a time** — which is not quite the same statement as "correct
for the current deployment," since the MCP server means that precondition
is not actually always true today. The honest, narrow claim this PR
stands behind is stated in §12.

## 9. Honest residual risk

- Under pathological lock contention (a competing process holding a raw
  write lock for an extended period), `delete_session()`'s wall-clock
  latency before reporting `PENDING` is not tightly bounded by
  `_DELETE_REQUEST_BUDGET_S` — disclosed in code, not fixed in this pass.
  It does still return (never hangs forever) and never misreports a
  pending outcome as success.
- `PENDING` resolution depends on the original background thread
  attempt eventually completing and the process staying up long enough
  for its `done_callback` to run, or on an explicit
  `check_pending_logical_deletions()` retry. A process restart between a
  `PENDING` report and the background thread's natural completion would
  lose that specific callback resolution — the durable
  `pending_logical_deletion.json` ledger entry survives the restart
  either way and remains visible to `check_pending_logical_deletions()`
  for retry, but the retry itself re-attempts the full operation rather
  than resuming the original in-flight one.
- **Corrected, elevated risk (§8.3): the multi-process exposure is
  present today**, via `orca/mcp/memory_server.py` running concurrently
  with `orca serve`, not merely a future `workers=N` scenario. Measured
  directly: a ~40–45% silent read-after-write miss rate under realistic
  concurrent load, and a confirmed `InternalError` + persistent
  in-process cache-poisoning failure mode on top of that. An advisory
  cross-process lock does not fix it (tested, not assumed). No safe,
  in-scope mitigation is implemented in this PR — see §8.3 for why a
  quick patch was rejected rather than attempted and shipped unverified.
- The migration path that would actually fix §8.3 (chromadb's
  client-server mode, §8.1 Option 2) is not implemented or scheduled.

## 10. User-visible status mapping (directive requirement #7)

`DeletionResult(logical_deleted: bool, physical_reclamation: str)` already
distinguishes the four required states; no new status enum was needed:

| Required state | Representation |
|---|---|
| Logical deletion confirmed | `logical_deleted is True` |
| Cleanup pending | `logical_deleted is True and physical_reclamation == DEFERRED` |
| Cleanup verified | `logical_deleted is True and physical_reclamation in (RECLAIMED, NOT_APPLICABLE)` |
| Deletion unsuccessful or indeterminate | `logical_deleted is False` (`physical_reclamation` is `FAILED` or `PENDING`) |

## 11. Acceptance tests

All in `tests/test_memory_long_term_chroma_privacy.py` and
`tests/test_deletion_end_to_end.py`, **14 passing**, confirmed stable
across 5 repeated full-suite runs (no flakiness observed). The full
canonical CI suite (`scripts/ci/run_deterministic_tests.sh`) was also run
in its entirety: **sentinel isolation 13 passed**; main suite **8597
passed, 8 failed, 293 skipped, 43 deselected, 4 xfailed** — the 8 failures
are pre-existing and unrelated to this PR (`tests/rse/test_block1_*.py`,
`tests/rse/test_imp4_ocr1.py` — RSE/Decision-9 program tests this PR does
not touch; `tests/test_eval_sandbox_docker.py::test_environment_has_no_host_secrets`,
decorated `@requires_docker`, environment-dependent — the sibling Docker
tests in the same file passed). No authorization, training-gate, or
acceptance-register test is touched by this PR's diff.

- Logical deletion removes data from every read path, including with
  another live collection sharing the file (raw-byte level, not just the
  query API).
- VACUUM failure/timeout does not block logical deletion; reports
  `DEFERRED`, not silently.
- The bounded timeout keeps `delete()` well under the old unbounded
  behavior for a simulated stuck VACUUM.
- A `DEFERRED` reclamation is durably ledgered, survives a simulated
  restart (fresh ledger read), and is cleared by a later successful retry.
- A successful VACUUM self-heals every other session's earlier-deferred
  entries, not just its own (real, non-mocked VACUUM).
- The full account-deletion cascade (`_delete_session_data`) reports
  `logical_deleted=True` and a valid `physical_reclamation` across every
  still-active memory store, with real chromadb, not a mock.
- **New**: `test_chromadb_persistent_client_is_not_a_safe_cross_process_interface`
  — regression-guards the exact finding that killed Attempt B (§4): a
  chromadb client built in a fresh OS process can fail to see a
  collection a different process's client just created and populated,
  while the data remains fully present in the original process. Documents
  *why* this codebase never routes a real deletion through a
  freshly-started separate process, as an executable fact rather than
  only a design-doc claim.
- **New**: `test_concurrent_real_processes_can_silently_miss_a_just_written_fact`
  — reproduces the §8.3 finding directly: genuine overlapping real-process
  access can silently miss a just-written fact, or raise a real
  `InternalError` with persistent in-process cache poisoning. Verifies
  the one invariant that must hold regardless (checked from an
  independent third process, never party to the race): the underlying
  write is never actually lost — this is a visibility/availability bug,
  confirmed, not a data-loss bug.

## 12. Final status

**ARCHITECTURE_DECISION_REQUIRED** — not `READY_FOR_INDEPENDENT_RETEST`,
per the explicit correction in §8.3. Tests passed vs. guarantees
established, stated separately as required:

- **Tests passed**: 14/14 in this PR's own targeted suite (stable across
  5 runs); 8597/8605 applicable in the full repo suite (8 pre-existing,
  unrelated failures, detailed in §11); sentinel/training-authorization
  hygiene unaffected (13/13).
- **Guarantees actually established**: the tombstone/ledger design in §5
  is correct for deletion requests made while **no other process holds a
  chromadb client against this store at that moment** — a precondition,
  not an ambient fact about the current deployment, now that
  `orca/mcp/memory_server.py` is confirmed to run as a genuinely
  independent process against the same store.
- **Guarantee NOT established**: that the current deployment is safe
  under real concurrent API/MCP access. It is not — measured directly at
  a ~40–45% silent-miss rate for ordinary reads, with a confirmed,
  more severe `InternalError` + cache-poisoning mode on top, and a tested,
  rejected naive fix (advisory locking). No change in this PR claims to
  resolve this; it is reported as the open architectural dependency.
- **The unresolved dependency**: migrating to chromadb's client-server
  mode (§8.1 Option 2), which requires migrating every chromadb call
  site in this codebase (store/recall/delete across `LongTermMemory` AND
  `DocStore`), not just the deletion path this PR touches, and standing
  up new operational infrastructure (a Chroma server process/service:
  deployment, health checks, availability story). That is a distinct,
  resourced architectural decision for an operator to make — named here
  precisely, not left vague, and explicitly out of this PR's scope to
  resolve unilaterally.
- Per directive requirement: MCP functionality is NOT removed, deployment
  topology is NOT silently changed, and the existing privacy changes
  (§1–§7) and their audit evidence are preserved unmodified by this
  finding.
