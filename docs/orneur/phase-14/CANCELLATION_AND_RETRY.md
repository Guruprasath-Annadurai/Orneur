# Phase 14 §28-34 — Budget, Deadline, Cancellation, Retries, Outcome-Unknown

## Cognitive budget (spec §28, §69)

Confirmed by reading `orca/cognitive/contracts.py` and
`orca/agent/delegation.py`: `CognitiveBudget` (with
`MODEL_CALLS`/`TOOL_CALLS`/`RETRIEVAL_CALLS`/etc. as named dimensions,
each a `max_*`/`consumed_*` pair) is **one object, per top-level
request**, threaded through delegation via `BudgetDimension` enum
mappings (`delegation.py:68-70`) rather than reconstructed at each
hop. `orca/society/budget_ledger.py`'s `SocietyBudgetLedger` explicitly
wraps this *same* object "for the duration of a single Court/Society/
Truth-Fabric/replanning invocation" — its own docstring states it is
never a shared global. This is the correct shape for spec §28's
requirement ("no new worker may reset MODEL_CALLS/TOOL_CALLS/..."): as
long as the same `CognitiveBudget` instance (or a value carried
faithfully across a process boundary, e.g. serialized into a
request payload and reconstructed with its `consumed_*` fields intact)
is what a delegated/remote call receives, nothing resets it.

**Not independently re-verified this phase**: whether every current
call site that crosses a real process boundary (e.g. a future
Gateway-to-inference-worker RPC) actually serializes and restores the
FULL budget object including its `consumed_*` fields, versus
accidentally passing only the request payload and implicitly starting a
fresh budget on the other side. Today's Gateway calls are in-process
(same Python object reference, not a network call), so this risk does
not yet manifest — it becomes real the moment Gateway-to-worker
communication crosses an actual process/network boundary, which has
not been built yet (see `MULTI_WORKER.md`'s "not executed" list). Flagged
here as the concrete thing to verify first if that RPC boundary is ever
added.

## Deadlines (spec §31)

`CognitiveBudget.max_latency_ms`/`consumed_latency_ms` is the existing
mechanism. Same finding as above: it is carried on the one budget
object, not recreated — but no dedicated test in this codebase (before
or during this phase) specifically asserts "a downstream call's
deadline never exceeds the upstream caller's remaining budget" as an
executable property. This is a real, disclosed test-coverage gap, not
a claim that the property currently fails.

## Cancellation (spec §30)

Not modified this phase. `orca/serve/api.py`'s streaming endpoints
(`/api/stream`) rely on FastAPI/Starlette's standard client-disconnect
detection to cancel the underlying `asyncio` task; this predates Phase
14 and was not re-tested here. A dedicated distributed-cancellation
test (client disconnects while a request has already crossed into a
separate inference-worker process) was not built — the Gateway today is
in-process, so there is no real second process to propagate a
cancellation *to* yet; this becomes a real requirement once Gateway
worker calls cross an actual process boundary.

## Retries and OUTCOME_UNKNOWN (spec §32-34)

No generic retry middleware exists in this codebase (confirmed by
`grep` during the Phase 14 state audit — the only retry logic found,
`retry_transient_async`, is scoped narrowly to `orca/truth/truth_fabric.py`'s
own transient-timeout classification, not a blanket wrapper). This
matches spec §32's explicit instruction ("do not implement generic
retry middleware around everything"). Connector writes already use
Phase 9's idempotency-key mechanism (proven independent of authorization
gating in Phase 13.3's connector multiprocess E2E test). No new
`OUTCOME_UNKNOWN` sentinel was added this phase — the existing pattern
(a post-commit crash or lost response is treated identically to normal
lease exhaustion — deny further consumption, never blindly retry) from
Phase 13.3's `CRASH_CONSISTENCY.md` is the reused architecture spec §34
asks for; it was not extended to new call sites this phase since no new
non-idempotent distributed call site was introduced.
