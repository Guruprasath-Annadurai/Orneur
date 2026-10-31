# L03 Phase B — vector isolation architecture

## Requirement
A problematic vector operation must not be able to consume application request capacity indefinitely without a bounded failure signal or controlled recovery. Baseline measurement: it can freeze the whole serving process for the lock duration (17.6 s `/livez` for an 18 s lock) and `Future.result(timeout=…)` does not help against a native call that holds the GIL.

## Alternatives evaluated
| Option | Verdict | Why |
|---|---|---|
| **Embedded chroma (baseline)** | rejected as the server default | cannot enforce a deadline; GIL freeze measured; per-session clients leak ~4 descriptors each. Kept as the transport for CLI tools/tests/non-POSIX, reported honestly as `deadlines_enforced: false` |
| **Threads + `Future.result(timeout)` (existing)** | rejected | measured 4× overshoot (19.7 s for a 5 s budget); cannot release a GIL-holding native call |
| **Process per operation / per conversation** | rejected | a process per operation costs a chromadb start (~0.5 s) each time and was previously reported to hit cross-process catalog problems; a process per conversation explodes. (The visibility problem was **not** reproduced on 1.5.9 — E9 — but nothing here depends on that) |
| **One supervised owner process per data directory over a private Unix socket (selected)** | **implemented** | the application never runs chromadb; the deadline is enforced on the *socket* so the application thread is released whatever the owner is doing; a single owner means no cross-process catalog is relied on; SQLite makes killing a stalled owner safe |
| A different vector database / server mode (e.g. a network Chroma server, Qdrant, sqlite-vec) | **not chosen — BLOCKED for CTO/founder** | would be a data-format and backend migration; requires a decision on data migration and operations. Comparison below |
| WAL/`busy_timeout` tuning inside chromadb | not available | `Settings` exposes no local-mode bound (checked in the existing P1 design record); patching chromadb internals was ruled out |

### Comparison with a backend switch (not implemented)
A network Chroma server or another engine would also remove the GIL coupling and could remove the single SQLite writer lock, but needs: a new service to run and secure, a re-embedding or export/import of every collection (incompatible format), new deletion/erasure semantics to re-prove (the `embeddings_queue` finding shows engine-specific retention), and backup integration (B6) rewritten. None of that was authorised. The selected design keeps the engine, the data format and the on-disk location; it can be placed in front of a different engine later because every operation already goes through `ChromaHost`.

## Design (as built)
```
application workers (any number)            owner (exactly one per data directory, flock)
  LongTermMemory / DocStore / reconcile        orca/vectorstore/server.py
  └ orca/vectorstore Collection/Store          ├ read lane  (4 workers, bounded queue 32)
    └ ServiceTransport  ── Unix socket ──────► ├ write lane (2 workers, bounded queue 32)
       · deadline on the socket                ├ per-collection in-flight cap (2) → "busy"
       · read/write admission (8 / 3 + 16 wait)└ ChromaHost → chromadb.PersistentClient(s)
       · supervisor: probe after a failure,       · shared/exclusive gate (delete, vacuum, rebuild, recycle exclusive)
         SIGKILL an unresponsive owner,           · client recycling: close+reopen above 32 open collections or 70 % of the
         verify pid really is our owner             descriptor limit (releases every descriptor, measured)
```
* **Transport**: JSON frames over `AF_UNIX`, socket mode 0600 in a 0700 per-user run directory, random token compared in constant time, no pickle, 64 MiB frame cap, request root must lie inside the data directory.
* **Bounded everything**: client in-flight (read 8 / write 3), client waiting 16 for ≤ 2 s, owner connections 64, owner queues 32 per lane, per-collection in-flight 2. Beyond a bound the answer is immediate `busy` (HTTP `server_busy` 503), never an unbounded queue.
* **Deadlines**: default 5 s, enforced on the socket (`socket.timeout` at the deadline); the owner drops requests whose deadline passed before they start.
* **Supervisor** (client side): after a timeout/unreachable call, probe once off the request path; an owner that cannot answer a ping, or whose oldest running job exceeds 8 s, is SIGKILLed (after `/proc/<pid>/cmdline` confirms it is our owner) and the next call starts a new one. Starting is serialised by a spawn lock; the owner never becomes a zombie (reaper thread); a replaced owner is detected, not assumed.
* **Lifecycle**: the owner exits by itself after 300 s idle (releases every file), above a memory limit (1536 MB; chromadb does not return memory on close — measured), or on SIGTERM. `orca vector status|stop` for operators.
* **Correctness semantics kept**: `Collection` handles never create (a stale handle after a deletion fails instead of re-creating the collection); deletion is reported removed only after listing proves the collection gone; vacuum removes orphaned segment directories.
* **Ownership**: each collection is bound to `sha256(salt + full session id)` in a sidecar database in the same directory; opening with a different binding is refused (`mismatch`) and neither read nor written; deletion by name is refused for a foreign binding; legacy (unbound) collections are **adopted** by the first opener and counted (`adopted_legacy`). A conversation with a deletion tombstone cannot open a collection at all (fails closed).
* **Mode**: `ORNEUR_VECTOR_MODE=service|embedded|auto` (auto = service inside `orca serve`, embedded elsewhere). Chromadb is an optional extra: the shipped container image does not install it, so there the layer reports `available: false` and everything uses the keyword path exactly as before.

## What this does and does not achieve
Achieved (measured, see benchmark and failure documents): the serving process stays responsive during a vector stall (`/livez` worst 0.02 s over 62 probes vs 17.6 s); callers are released at their deadline (5.02 s for a 5 s deadline vs 19.7 s); stuck writes can only fill their own bounded lane and further writes are refused immediately; a killed owner is replaced in a median 0.48 s; a frozen owner in ~6.9 s; the application process holds 4 descriptors regardless of conversation count (baseline 818 at 200) and never loads chromadb.
**Not achieved, stated plainly:**
* While a *foreign* process holds the database write lock, a freshly started owner cannot initialise its Chroma client; if the stall froze the old owner's whole interpreter, vector **reads** also wait until the foreign lock ends (the application is still responsive and gets bounded errors). About one trial in three at baseline froze the interpreter.
* The owner itself is a single point of failure for vector features (not for chat: derived memory writes degrade and are counted; explicit remember/recall return 503/504).
* Platform: POSIX only (Unix sockets, `flock`, `/proc`); elsewhere the embedded transport applies and no containment is claimed.
* The 8 s "stuck" threshold, 5 s deadline and lane sizes are conservative defaults, not tuned.
* Restore/move of the data directory must stop the owner first (see the blocker register: integration with B6).
