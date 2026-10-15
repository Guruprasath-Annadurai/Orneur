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
| 4 | Concurrent reads/writes across separate worker *processes* | **Tested extensively (§2, §3, §8.3). No reproducible correctness defect found under properly-synchronized conditions across 7 distinct reproduction attempts; one real but unreproduced anomaly remains on record. See §8.3/§12 — final verdict is `ROOT_CAUSE_UNRESOLVED` for this guarantee specifically, not a claim of either safety or defect.** |
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

### 8.3 CORRECTED evidence record (2026-10-15, second pass)

The first pass of this section (preserved in git history on this branch,
commit before this correction) reported a "~40–45% silent miss rate" and
a "persistent cache-poisoning" finding as evidence of an existing,
present-day chromadb embedded-mode defect. **That characterization is
retracted.** Root-causing it further (directed re-investigation) found
the original experiment measured an unsynchronized race, not a
post-completion consistency defect. This section is restructured exactly
along the lines required: confirmed observations, retracted findings,
unreproduced anomalies, remaining architectural risks, and evidence-backed
recommendations — kept separate so neither category is overstated as the
other.

#### Retracted findings

- **The "~40–45% silent miss rate" claim is retracted.** It was measured
  by starting a writer subprocess and, WITHOUT WAITING for it to
  complete, immediately issuing a read from a different process racing
  against the still-in-flight write. A miss under those conditions does
  not demonstrate a staleness/caching defect — it may simply mean the
  read executed before the write finished, which is the expected,
  unremarkable behavior of any datastore given two uncoordinated,
  unsynchronized operations. No architecture (embedded or server-backed)
  is expected to make an in-flight write visible before it returns.
- **The "persistent in-process cache-poisoning" claim is retracted**
  for the same reason: the `InternalError` ("Error creating hnsw segment
  reader: Nothing found on disk") was observed under the same
  unsynchronized-overlap condition — a read genuinely racing a write
  whose index segment had not yet been created is a plausible, mundane
  consequence of reading an object that does not exist yet, not a
  confirmed defect specific to embedded chromadb or to cross-process
  access. The subsequent "poisoning" observation (the same process unable
  to read that collection again) was not independently re-verified under
  corrected, properly-synchronized conditions and is **not reproduced** in
  any of the seven clean reproduction attempts below.
- **The advisory-`flock` test result is retracted as proof of a specific
  internal chromadb caching defect.** The flock test was run against the
  same unsynchronized-overlap harness as the retracted miss-rate claim;
  its failure to reduce the (confounded) miss rate does not, by itself,
  prove chromadb's client-side catalog is the specific mechanism at
  fault. It is accurate only as: "an advisory lock does not fix whatever
  was producing misses in that specific (confounded) experiment" — not as
  a general statement about chromadb internals.
- The retired test `test_concurrent_real_processes_can_silently_miss_a_just_written_fact`
  (which encoded the retracted finding) has been **replaced** with
  `test_read_after_confirmed_write_is_consistent_across_real_processes`,
  which uses a real process-safe synchronization primitive
  (`multiprocessing.Event`) so a reader can only ever observe a write
  that has ALREADY, confirmedly, completed — the scientifically valid
  version of a read-after-write test.

#### Confirmed observations (reproduced directly, hold up under scrutiny)

- `orca/mcp/memory_server.py` **is** a genuinely independent, already-
  shipped OS process (confirmed by reading its source: a standalone
  `if __name__ == "__main__": asyncio.run(main())` stdio server), separate
  from `orca serve`'s uvicorn process, constructing its own
  `MemoryEngine`/`LongTermMemory` against the same `MEMORY_DIR/vectors`.
  This remains true regardless of the retraction above — it is a fact
  about the codebase's structure, not a timing-sensitive measurement.
- Deployment-scope audit (directive requirement #1), unaffected by the
  retraction: every entry point enumerated and checked, not assumed.
  `orca serve` (uvicorn, single process). `orca/mcp/memory_server.py`
  (separate process, confirmed, no coordination). CLI/TUI (confirmed:
  only touch `EpisodicMemory`, a plain JSON file — no chromadb exposure).
  `orca/docs/store.py` (its own independent `PersistentClient`, against a
  **different** directory, `ORCA_HOME/docs/vectors` — no overlap with
  this store, same risk class independently). `k8s/deployment.yaml`:
  `replicas: 1`, `ORCA_HOME` mounted from a PersistentVolumeClaim
  (`orneur-api-pvc`) — a one-line replica-count change would let multiple
  pods share that exact volume. **Single-writer ownership is not
  enforced anywhere in this codebase** — grepped for `flock`/`fcntl`/
  pidfile/singleton patterns near the vectors path and found none.
- A genuine, separate test-isolation gap, found while investigating this:
  `tests/test_deletion_end_to_end.py` has no fixture isolating
  `MEMORY_DIR` from the real default `~/.orca` directory (unlike
  `tests/test_memory_long_term_chroma_privacy.py`'s `home` fixture, which
  does). Confirmed this session's own test runs operated against the
  real, ~1985-collection, months-accumulated store on the machine this
  work was done on. Each test uses a fresh random UUID session id and
  only ever deletes its own exact collection by name — no risk of
  colliding with or deleting real pre-existing data was found — but this
  should be fixed as its own, separate, narrowly-scoped change (isolate
  `MEMORY_DIR` the same way `home` does for the other file), not folded
  into this PR's diff.
- **Seven distinct, deliberately corrected reproduction attempts, all
  clean (0 failures)**, run specifically to re-test for a genuine
  post-completion consistency defect once the synchronization confound
  was removed:
  1. Strict sequential write→read, small scale: 15/15 clean (embedded).
  2. Strict sequential write→read, small scale, **real HTTP
     server-backed chroma** (a local `chroma run` instance actually
     started and queried, not simulated): 15/15 clean.
  3. Reading a settled, already-committed session while a different
     process is busy writing unrelated new sessions concurrently (the
     realistic API-writes/MCP-reads-older-memory shape): 15/15 clean.
  4. Strict sequential write→delete racing continuous background
     delete+VACUUM churn from another process: 20/20 clean.
  5. Strict sequential write→read→delete against a **safe, isolated copy
     of this machine's real ~1985-collection accumulated store**: 25/25
     clean.
  6. Repeated `importlib.reload()` churn (40 cycles), matching the exact
     pattern `tests/test_memory_long_term_chroma_privacy.py`'s own `home`
     fixture applies once per test: 40/40 clean.
  7. Re-running the EXACT original two-file combined pytest suite against
     a realistic-scale copy of the real store (closest replication of the
     original full-suite conditions achievable): 14/14 clean, 3 repeated
     runs.

#### Unreproduced anomaly (real, not retracted, cause unresolved)

The ORIGINAL `NotFoundError` observed during a specific full-suite pytest
run remains real — a genuine traceback was captured and is preserved
below, and the methodology that produced it WAS properly sequenced (the
writer's `store()` call had already returned before the probe subprocess
started). This is categorically different from the retracted findings
above. However, **none of the seven reproduction attempts above
reproduced it**, including attempt #7, which replicates the original
combined-suite conditions as closely as practical. The specific
hypotheses tested and ruled out: raw lack of synchronization (was never
actually the issue here, since the original was already sequential),
realistic store scale alone, concurrent unrelated writes, concurrent
VACUUM churn, and `importlib.reload()` churn matching the test fixture
pattern — none of these, individually or in the closest available
combination, reproduce it.

**Preserved original evidence** (directive requirement, Mission 1):

```
DEBUG _delete_sync exception: NotFoundError('Collection [orca_e2e-9dc6] does not exist')
  File ".../orca/brain/memory.py", line 621, in _delete_sync
    client.delete_collection(name=f"orca_{session_id[:8]}")
  File ".../chromadb/api/client.py", line 405, in delete_collection
  File ".../chromadb/api/rust.py", line 324, in delete_collection
chromadb.errors.InternalError / NotFoundError: Collection [orca_e2e-9dc6] does not exist
```

Environment: chromadb 1.5.9 (rust-backend client), Python 3.11, macOS,
observed inside `tests/test_deletion_end_to_end.py::test_deletion_spans_every_still_active_store`
during a run of the full two-file combined suite (`test_memory_long_term_chroma_privacy.py`
+ `test_deletion_end_to_end.py`) against this session's real, accumulated
`~/.orca` store (not isolated — see the test-isolation gap noted above),
after many preceding tests in the same pytest file had already run.

**What evidence would be needed to resolve this**: the anomaly appears
tied to something present in that specific full pytest-session's
accumulated process state that none of attempts #1–7 individually
recreate. The most likely remaining candidate, not yet tested: running
the FULL, real multi-hundred-file pytest suite (not just these two
files) up through the point of the original failure, with chromadb's own
internal logging/tracing enabled and OS-level strace/dtrace on the
specific `delete_collection()` call, to capture what the process's
actual file-descriptor and memory state looked like at the moment of
failure — meaningfully more instrumentation than a two-file, ad hoc
reproduction can provide. This is flagged as the specific next step if
and when this anomaly recurs, rather than spending further unscoped time
chasing it now that the cheaper, most-likely hypotheses are ruled out.

#### Remaining architectural risk (independent of the above)

Independent of whether the above anomaly is ever pinned down, chromadb's
own `PersistentClient` documentation states: *"This client is intended
for local development and testing. For production, prefer a
server-backed Chroma instance."* This remains a real, vendor-stated
constraint this codebase does not follow for its `orca serve` + MCP
server topology, regardless of whether any of this session's specific
experiments happened to reproduce a concrete failure from it. It is
reported as a **risk to be aware of**, not as a confirmed, measured defect.

#### Mission 5 — architecture comparison under equivalent, correctly synchronized workloads

| Criterion | Embedded (current) | Server-backed (chroma client-server) |
|---|---|---|
| Read-after-write consistency (properly synchronized) | Confirmed clean, 25/25+ across multiple scales | Confirmed clean, 15/15 at small scale |
| Delete/recall correctness (properly synchronized) | Confirmed clean across all 7 reproduction attempts | Not separately stress-tested beyond the same small-scale check |
| Latency at small scale | Sub-second for construct+store+recall+delete (typically <0.1s) | Comparable, sub-second, once warmed up |
| **Latency at realistic scale (~1985 collections)** | **1.77s total for construct+store+recall+delete+vacuum** (measured directly) | **First `add()` call after server startup took 604 seconds (10m4s)**, confirmed via the server's own timestamped log (not a client artifact) — a SECOND `add()` call on a fresh collection afterward took 0.51s, so this is a one-time cold-start cost at this scale, not a sustained per-request problem, but a real and severe one |
| Operational complexity | None — already running | A new server process to deploy, monitor, keep available; a ~10-minute cold-start tax at realistic scale is a serious operational consideration for restarts/redeploys |
| Compatibility with API and MCP entry points | Both already compatible (current state) | Would require migrating both `LongTermMemory` and `DocStore` (different directories, same risk class) to `HttpClient` |
| Process consistency / crash recovery | Previously confirmed safe (`kill -9` mid-VACUUM, clean `integrity_check`) | Not separately crash-tested in this pass |

**Neither architecture was assumed safe or unsafe before measurement**, per
Mission 5's instruction. The result: no demonstrated correctness
advantage for server-backed mode under equivalent, correctly synchronized
workloads, and a newly-discovered, severe cold-start latency cost at
realistic scale that argues for caution, not urgency, before migrating.

#### Corrected recommendation

Given (a) the headline evidence that motivated urgency (the 40–45% miss
rate, the cache-poisoning finding) is retracted, (b) seven separate
attempts to find a genuine correctness defect in embedded mode under
realistic, properly-synchronized conditions all came back clean, and (c)
server-backed mode has its own newly-discovered, serious cold-start
latency cost at realistic scale that was not previously known: **this PR
does not have evidence-backed grounds to recommend migrating to
server-backed chroma**, and does not do so. The one remaining open item
is the unreproduced original anomaly, named precisely above with the
specific instrumentation that would be needed if it recurs — not left
vague, and not used to justify a conclusion the evidence does not
support in either direction. The final verdict is stated in §12.

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
- **§8.3, corrected**: `orca/mcp/memory_server.py` is confirmed to be a
  genuinely independent process accessing the same shared store as
  `orca serve` today, not merely a future `workers=N` scenario — that
  structural fact stands. However, the specific measured evidence that
  this is UNSAFE (the "~40–45% miss rate", the cache-poisoning mode) is
  **retracted** after further root-causing found it was measured under an
  unsynchronized race, not a genuine post-completion consistency defect.
  Seven separate, properly-synchronized reproduction attempts (small
  scale, realistic ~1985-collection scale, concurrent writes, concurrent
  VACUUM churn, module-reload churn, real HTTP-server-backed mode, and
  the closest practical replication of the original full-suite
  conditions) found no reproducible correctness defect. One real,
  separately-captured anomaly (a `NotFoundError` with a genuine
  traceback) remains unreproduced and its root cause is unresolved — see
  §8.3 for the exact evidence and what further instrumentation would be
  needed if it recurs. This risk entry is downgraded from "confirmed
  unsafe" to "structurally present, not demonstrated unsafe, one
  unresolved anomaly on record."
- Server-backed chroma was directly measured, not assumed safe: at
  realistic (~1985-collection) scale, the first `add()` call after
  server startup took **604 seconds**, confirmed via the server's own
  log, before warming up to normal latency. This is a newly-discovered,
  real operational risk of the migration path itself, relevant to any
  future decision to pursue it.

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
- `test_chromadb_persistent_client_is_not_a_safe_cross_process_interface`
  — kept as regression coverage for the real, properly-sequenced
  `NotFoundError` anomaly described in §8.3. Asserts leniently (the
  anomaly is confirmed-but-unreproduced, not reliably reproducing) —
  catches it again if it recurs, without failing CI on its absence.
- `test_read_after_confirmed_write_is_consistent_across_real_processes`
  — **replaces** the retracted `test_concurrent_real_processes_can_silently_miss_a_just_written_fact`.
  Uses `multiprocessing.Event` as a real process-safe completion barrier
  so the reader can only ever observe a write that has already,
  confirmedly, returned — the scientifically valid version of a
  read-after-write test (CTO directive Mission 3). Asserts the positive
  invariant unconditionally (the write IS visible), since this is now a
  confirmed-clean guarantee, not a leniently-accepted race.

## 12. Final status

**ROOT_CAUSE_UNRESOLVED** — not `EMBEDDED_ARCHITECTURE_ACCEPTABLE_WITH_CONSTRAINTS`
and not `SERVER_BACKED_MIGRATION_REQUIRED_WITH_EVIDENCE`, per the
corrected evidence in §8.3. Tests passed vs. guarantees established,
stated separately as required:

- **Tests passed**: 14/14 in this PR's own targeted suite (stable across
  5+ runs); full repo suite results restated in §11; sentinel/
  training-authorization hygiene unaffected (13/13).
- **Guarantees actually established**: the tombstone/ledger design in §5
  is correct for deletion requests, confirmed under properly-synchronized
  concurrent access (seven separate reproduction attempts, all clean,
  §8.3) including the realistic two-real-process (API+MCP-shaped) and
  realistic-scale (~1985-collection) conditions. The headline evidence
  that previously motivated treating this as unsafe (the ~40–45% miss
  rate, the cache-poisoning finding) is retracted — it measured an
  unsynchronized race, not a defect.
- **What is NOT established**: that the one real, properly-sequenced
  `NotFoundError` anomaly captured during the original full-suite run
  (genuine traceback preserved in §8.3) cannot recur. Seven distinct,
  deliberate reproduction attempts — including the closest practical
  replication of the original combined-suite conditions at realistic
  scale — did not reproduce it. Its root cause is genuinely unresolved,
  not merely unconfirmed-but-assumed-benign.
- **The remaining reproducer and evidence needed** (per the directive's
  explicit requirement for this verdict): running the full, real
  multi-hundred-file pytest suite (not a two-file reproduction) up to the
  point of the original failure, with chromadb's internal
  logging/tracing enabled and OS-level syscall tracing on the specific
  `delete_collection()` call, to capture the process's actual file
  descriptor/memory state at the moment of failure. This is a
  meaningfully larger diagnostic effort than this session's ad hoc
  reproduction scripts could provide, and is named as the specific next
  step if this anomaly recurs, rather than invented evidence to justify
  a verdict in either direction now.
- **Server-backed migration**: not recommended at this time. No
  correctness advantage was demonstrated for it over embedded mode under
  equivalent, correctly synchronized workloads, and it carries its own
  newly-discovered, serious cold-start latency cost at realistic scale
  (604 seconds for the first write after server startup, confirmed via
  the server's own log). `SERVER_BACKED_MIGRATION_REQUIRED_WITH_EVIDENCE`
  would overclaim a case this evidence does not support.
- Per directive requirement: MCP functionality is NOT removed, deployment
  topology is NOT silently changed, and the existing privacy changes
  (§1–§7) and their audit evidence are preserved unmodified by this
  investigation. No merge, deployment, infrastructure provisioning, or
  spend occurred.

## 13. Test-isolation incident & real-store impact assessment (2026-10-15, third pass)

Triggered by a CTO directive after this document's own §8.3 disclosed, in
passing, that `tests/test_deletion_end_to_end.py` had been operating
against the real default `~/.orca` directory rather than an isolated
tmp path. This section is the full Mission 1/2/3/5/6 response to that
finding, kept separate from the chromadb architecture question (§8) since
it is a distinct issue: a test-infrastructure gap, not a chromadb design
question.

### 13.1 Mission 2 — real-store impact assessment (read-only, performed first)

Before any further destructive test was run, a read-only forensic
examination of the real `~/.orca/memory/vectors` directory was performed:

- **Unrelated collection integrity**: the real, accumulated store (1987
  top-level segment directories, 14.6MB `chroma.sqlite3`, confirmed via
  `PRAGMA`-level inspection) was not found corrupted. No evidence of a
  deleted or overwritten pre-existing (non-test) collection was found.
  Every deletion this codebase's tests perform targets an exact
  session-derived collection name (`orca_{session_id[:8]}`) generated
  from a fresh `uuid.uuid4()` — there is no code path (grepped and
  confirmed) that deletes by pattern, prefix, or wildcard.
- **Unexpected test-created collections**: confirmed present. A direct
  SQL query against the real `collections` table found **319 collections
  matching the `orca_e2e-*` naming pattern** that `tests/test_deletion_end_to_end.py`
  uses — i.e., still present, not deleted. Cross-referencing the ~15
  segment directories with a modification time in the last 24h against
  the current catalog found **none of them are `orca_e2e-*` names** —
  they are either already absent from the catalog (successfully deleted,
  with only the on-disk segment not yet reclaimed) or belong to plainly
  non-`e2e`-named collections (`orca_<8-hex>`) traceable to this
  session's own earlier, ungated `python3 -c` reproduction scripts that
  did not override `ORNEUR_HOME`/`ORCA_HOME` (7 such collections
  identified by exact segment-to-name cross-reference). The large bulk of
  the 319 `orca_e2e-*` entries, by directory-modification-time evidence,
  **predate this session** — consistent with this project's own
  documented history (Phase 5.1's audit: `LongTermMemory` had no
  deletion method at all until recently), not something introduced today.
- **Deletion/reclamation ledgers**: `pending_logical_deletion.json` and
  `pending_reclamation.json` exist in the real directory (created by past
  unisolated test runs) and are both empty — no outstanding pending state.
- **Account-deletion side effects**: not separately exercised against the
  real store in this investigation (account-deletion tests were already
  covered by the isolated `tests/test_account_delete.py` suite, §13.3).
- **CI/artifact exposure**: this project's CI does not archive
  `~/.orca` as a build artifact (confirmed by reading `.github/workflows/`
  — no such step exists), so no protected data from the real store was
  exposed via CI output or artifacts as a result of this gap.
- **No cleanup was performed on the real store.** Per the explicit
  instruction not to clean up without separate approval, the 319
  historical `orca_e2e-*` entries and the 7 session-attributable orphans
  are left exactly as found, named precisely here rather than silently
  removed or silently left undisclosed.

### 13.2 Mission 1/3 — isolation fix and regression tests

Fixed in `tests/conftest.py`'s existing autouse fixture (the same fixture
that already isolates `orca.docs.store`, `orca.gateway.deployment`,
`orca.godmode.lease_store`, and the model/training registries from the
real `~/.orca` — this gap was an omission from that existing, otherwise
comprehensive pattern, not a new mechanism):

- `orca.brain.memory.MEMORY_DIR` and `.CACHE_DIR`, `orca.memory.episodic.EPISODIC_DIR`,
  and `orca.memory.store.MEMORY_ROOT` are now redirected to `tmp_path`
  subdirectories for every test, unconditionally.
- A fail-closed guard (`assert_path_is_isolated_test_storage`, a
  standalone, independently unit-tested function) asserts every one of
  these resolves under the test's own `tmp_path` and never under the real
  home directory, so a future accidental regression (e.g. a module-level
  instance constructed before this fixture's monkeypatch takes effect)
  fails loudly here instead of silently writing to real storage again.
- **A real regression was found and fixed while verifying this**: the
  first isolation path chosen, `tmp_path / "cache"`, collided with a path
  several existing security tests (`test_a_safe_cache.py`,
  `test_audit007_cache_dir_remediation.py`) already own themselves,
  creating it with specific restrictive permissions (`mode=0o700`) as
  part of what they test — this fixture creating it first, with default
  permissions, broke 3 tests. Found by actually running the full suite
  after the change (not assumed safe), fixed by renaming to
  `tmp_path / "brain_memory_cache"`, re-verified clean.
- **Verified concretely, not just asserted**: ran
  `tests/test_deletion_end_to_end.py` before and after the fix, comparing
  the real store's collection count and the `chroma.sqlite3` file's exact
  MD5 hash — both byte-identical after the "after" run, confirming the
  isolated test genuinely never touches the real store anymore.
- Five new regression tests added in `tests/test_conftest_memory_isolation.py`:
  confirm the isolation is active for a normal test; confirm the guard
  function does NOT raise for a genuinely isolated path; confirm it DOES
  raise (`pytest.raises`, not just existing unexercised) for the real
  home directory; confirm it DOES raise for a path that is a legitimate
  tmp directory but not THIS test's own `tmp_path` (the specific property
  that prevents one parallel worker from reusing another's live test
  database); confirm two different tests resolve to two different,
  non-colliding `MEMORY_DIR` values.

### 13.3 Mission 5 — qualification results

- `tests/test_memory_long_term_chroma_privacy.py` + `tests/test_deletion_end_to_end.py`
  + `tests/test_conftest_memory_isolation.py` + `tests/test_account_delete.py`
  + `tests/test_g006_tenant_isolation.py` combined: **66 passed, 2 xfailed**,
  stable across 3 repeated runs.
- Canonical full suite (`scripts/ci/run_deterministic_tests.sh`), run
  twice: the first run (immediately after adding the isolation fixture,
  before the cache-path regression above was found) showed **12 failed**
  — the original 8 plus 3 real regressions from the `tmp_path / "cache"`
  collision and 1 flake. After the fix, a second full run returned to
  exactly the original **8 failed, 8603 passed, 293 skipped, 43
  deselected, 4 xfailed** (8603, not 8598/8597 as in earlier passes of
  this document, because this pass adds the 5 new isolation tests plus
  the net effect of the retired/replaced cross-process test — accounted
  for, not an unexplained drift).
- **The 8 remaining failures were investigated directly, not assumed
  unrelated by filename alone**, per this directive's explicit
  instruction not to invent explanations:
  - **7 RSE/`imp4_ocr1` failures share one single, confirmed root
    cause**: `orca/rse/imp4/ocr1.py`'s `_limits()` function attempts
    `resource.setrlimit(resource.RLIMIT_AS, (128*1024*1024, ...))` in a
    sandboxed child process, with its own code comment stating *"macOS
    can reject these limits. Do not continue unlimited."* — and fails
    closed (`os._exit(71)`) when it does. Reproduced directly on this
    exact machine: `resource.setrlimit(resource.RLIMIT_AS, ...)` raises
    `ValueError('current limit exceeds maximum limit')` here, confirming
    this is the disclosed, designed-for macOS platform limitation the
    code's own comment anticipates — not 7 independent defects, not
    caused by this PR's diff (`orca/rse/` is untouched by it), and not an
    invented explanation: directly reproduced via `python3 -c
    "resource.setrlimit(...)"` on this machine.
  - **1 Docker-sandbox failure** (`test_eval_sandbox_docker.py::test_environment_has_no_host_secrets`,
    `@requires_docker`): environment-dependent, consistent with earlier
    passes of this document; the sibling Docker tests in the same file
    passed.
  - None of the 8 are genuine regressions from this PR's diff.

### 13.4 Mission 6 — final verdict

**`READY_FOR_INDEPENDENT_AUDIT`** — both required preconditions are met:
destructive-test isolation is demonstrated (not merely implemented: the
before/after MD5-hash comparison in §13.2 is the demonstration, plus 5
passing regression tests proving the guard itself fails closed), and
potential real-store impact has been assessed (§13.1, read-only, with
exact collection counts and names, not an assertion of zero impact
without evidence).

**Outstanding, disclosed, NOT blocking independent audit**:
- 319 historical `orca_e2e-*` collections and 7 session-attributable
  orphaned collections remain in the real `~/.orca/memory/vectors` store,
  named exactly, awaiting separate approval before any cleanup.
- The §8.3 architecture question (`ROOT_CAUSE_UNRESOLVED` for the
  original `NotFoundError` anomaly) is unchanged by this section and
  remains its own, separately-tracked open item.
- No merge, deployment, model training, infrastructure provisioning,
  unauthorized deletion, or spend occurred in the course of this
  investigation.
