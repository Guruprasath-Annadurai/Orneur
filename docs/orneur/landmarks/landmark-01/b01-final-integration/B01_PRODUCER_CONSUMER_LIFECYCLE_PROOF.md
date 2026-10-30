# B-01 — Producer/consumer lifecycle: defects, design, proof

Evidence state: **VERIFIED_ENGINEERING** (deterministic, engineering-owned).
Code: `orca/cognitive/streaming.py` (`RawDeltaChannel`, `KernelRun`), consumed by `orca/serve/api.py::_event_stream`.

## 1. The two defects in the PR #135 handoff (reproduced, not assumed)

`evidence/lifecycle_defect_repro.py` loads the **original** module straight from git (`15befec`) and runs the handoff's own lifecycle. Output (`evidence/lifecycle_defect_repro.output.txt`):

```
== 1. handoff lifecycle against the ORIGINAL channel (15befec) ==
HANG: the consumer waited 2s for a terminal signal that the sample only sends after the consumer has finished
== 2. close() on a FULL original channel ==
tasks before close()=1 after close()=2 -> UNTRACKED background task created
fail() on a full channel also spawned a task: True
== 3. the corrected bridge (this branch), same shape of use ==
terminated by itself: seen=['a', 'b', 'c'] result=RESULT state=ended terminal_observed=1
close() on a full channel: tasks before=3 after=3; drained=['x']
```

1. **Hang after the final token.** The sample iterated `async for raw_delta in channel` and only afterwards did `await kernel_task; channel.close()`. The iteration ends only when the terminal marker arrives, and the marker was sent *after* the iteration. A correct Kernel run would therefore wait forever (until the client or a server timeout ended it).
2. **Untracked terminal-enqueue task.** `close()`/`fail()` put their sentinel with `put_nowait`, and when the queue was full created a fire-and-forget `asyncio.create_task(self._q.put(...))`. That task has no owner, can outlive the request, and (if the consumer is gone) blocks forever on a queue nobody drains. (Part 3 of the output shows the leftover tasks from part 2 still alive in the same loop: `tasks before=3`.)

Merely moving `channel.close()` would not have fixed (2) and would leave the cancellation/full-queue cases unproven, so the bridge was redesigned.

## 2. Design

* **A channel has exactly one terminal state, held as an attribute** (`open → ended | failed | aborted`), set once; the first terminal state wins. It is never a queued item, so it needs no free slot and no task.
  * `close()` — producer finished: the consumer drains everything buffered, then sees a clean end.
  * `fail(exc)` — producer failed: the consumer drains everything buffered, then receives `exc` **once**.
  * `abort()` — the consumer is gone: the buffer is discarded and any producer parked in `push()` is woken and raises `ChannelClosed`.
* `push()` blocks while the buffer is full and **never discards**; every waiter is registered in a list and unregistered in a `finally`, so cancellation cannot leave a parked coroutine (`channel.waiting == 0` is asserted after every scenario).
* **`KernelRun` supervises the producer.** The producer wrapper itself reports its end (`close` on success, `fail` on any exception, `abort` on cancellation), so the consumer cannot hang whichever way the Kernel ends. `deltas()` is the consumer loop (optionally probing `is_gone()` every `poll_s` of idleness so a client that vanished while the model is silent is noticed). `aclose()` aborts the channel, cancels the producer, and **waits for it to finish** — including when `aclose()` is itself being cancelled (it keeps waiting, then re-raises) — and marks the task's exception retrieved.
* In the API, `_event_stream`'s `finally` always runs `await kernel_run.aclose()` before releasing the turn authority; the consumer loop is wrapped in `contextlib.aclosing(...)` so the `deltas()` generator is closed deterministically instead of by the garbage collector.

## 3. Required test matrix (all time-bounded, all assert cleanup)

`tests/test_b01_raw_delta_lifecycle.py` (21 tests, no network):

| Required scenario | Test |
|---|---|
| Successful stream closes automatically | `test_successful_stream_terminates_the_consumer_without_help`, `test_real_kernel_success_closes_the_stream_and_leaves_nothing_behind` |
| Provider yields zero chunks | `test_provider_that_yields_zero_chunks_terminates_safely`, `test_real_kernel_provider_with_zero_chunks`, live: `test_a_provider_that_answers_with_nothing_terminates_cleanly` |
| Provider fails before the first chunk | `test_provider_failing_before_the_first_chunk_reaches_the_consumer_once`, `test_real_kernel_provider_failure_before_the_first_chunk` |
| Provider fails after several chunks | `test_provider_failing_after_several_chunks_delivers_them_then_the_failure`, `test_real_kernel_provider_failure_after_chunks`, live: `test_S6_provider_dying_mid_stream_…` |
| Queue reaches maximum capacity | `test_queue_at_capacity_blocks_the_producer_and_never_drops` (12 items through a 2-slot buffer: `pushed == delivered == 12`), `test_closing_a_full_channel_needs_no_free_slot_and_creates_no_task` |
| Consumer disconnects while the queue is full | `test_consumer_disconnect_while_the_queue_is_full_releases_the_blocked_producer`, `test_real_kernel_disconnect_with_a_full_queue_closes_the_gateway_stream` (gateway stream closed exactly once, `_active_streams == 0`) |
| Producer cancelled while blocked on `push()` | `test_producer_cancelled_while_blocked_on_push_releases_the_consumer` |
| Terminal success/failure observed exactly once | `terminal_observed == 1` in the success/failure tests; the failure is raised once and a second read ends quietly; `test_first_terminal_state_wins_and_is_idempotent` |
| No orphan producer / terminal-enqueue task | every test compares `asyncio.all_tasks()` before/after; plus server-level `test_abandoned_streams_leave_no_task_stream_reservation_or_authority` (inspects the real server's event loop) |
| No leaked gateway connection | `runtime._active_streams == 0` and `stream_aclose_count == 1` in every real-Kernel test; live: the provider's `streams_open == 0` after Stop/disconnect |
| Cancellation terminates producer and consumer; cleanup survives a second cancellation | `test_a_cancelled_consumer_still_finishes_the_producer`, `test_consumer_gone_probe_raises_without_a_delta` |

Additional protocol tests: `test_receive_timeout_does_not_lose_or_duplicate_items`, `test_real_kernel_stop_mid_stream_stops_the_provider_early` (nothing more is produced after Stop), `test_on_served_is_announced_once_…`, `test_truth_fabric_draft_tokens_never_reach_the_raw_delta_hook`, `test_working_memory_ingestion_receives_the_redacted_answer_not_the_raw_one`.

Cursor's own `tests/test_kernel_streaming.py` (9 tests, including its live-Ollama case) passes unchanged against the new channel — the public API (`push`, `on_raw_delta`, `as_hook`, `close`, `fail`, `closed`, `maxsize`, async iteration) is preserved.

## 4. Server-level proof (real uvicorn socket, long provider generations)

`tests/test_b01_stream_cleanup.py` abandons 18 streams (before any byte / after the first chunk / after 20 chunks) against a provider whose generation would last ~30 s and then, on the **server's own event loop**, asserts: the provider stopped serving every abandoned stream within 5 s; no `kernel-run` task exists after 3 s; no stream-owned task (`kernel-run`, quota/authority heartbeats, `_event_stream`, `_releasing_iterator`, channel waiters) survives; quota drift is exactly the number of streams that had produced output; the count is stable (no stale reservation is refunded later); the conversations are immediately usable again.

**The test discriminates.** With `await kernel_run.aclose()` replaced by a no-op (`evidence/mutation_no_producer_cleanup.txt`) the test fails; with the real code it passes. The same mutation is also caught by `test_S4_S5_S6_S7_…` ("the provider was never told to stop").

## 5. Honest scope notes

* The knowledge-graph enrichment task that `_event_stream` spawns *after an accepted commit* (`asyncio.create_task(asyncio.to_thread(sess.knowledge_graph.extract_and_add, …))`) is pre-existing derived-state work, fire-and-forget by design, and is not part of the stream lifecycle. It is excluded from the "no surviving task" assertions by name and disclosed as limitation **L-03** in the blocker register.
* The channel is single-event-loop by design (documented in the module); it is not a cross-thread queue.
