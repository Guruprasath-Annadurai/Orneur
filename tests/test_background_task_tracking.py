"""
AUDIT-B81-A-P2-03 regression tests for orca.serve.api._track_background_task.

Root cause: asyncio.create_task(...) called with its return value
discarded (the exact pre-existing pattern at the knowledge-graph
extraction call site) leaves the event loop holding only a WEAK
reference to the task -- it can be garbage-collected mid-execution,
which is what produces "Task was destroyed but it is pending!". These
tests prove the fix: a task started through _track_background_task is
strongly referenced for its whole lifetime (survives an explicit gc.collect()
while still running), is removed from the tracking set once it finishes,
and a genuine exception is surfaced rather than silently swallowed.
"""
from __future__ import annotations

import asyncio
import gc

import pytest

from orca.serve import api as api_module


@pytest.mark.asyncio
async def test_tracked_task_survives_gc_while_still_running():
    """Reproduction of the actual defect: a bare asyncio.create_task(...)
    with no other reference can be collected while still pending. A task
    started via _track_background_task must not be collectible, because
    _background_tasks holds a real strong reference to it."""
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_work():
        started.set()
        await release.wait()
        return "done"

    task = api_module._track_background_task(slow_work(), name="test-survives-gc")
    await started.wait()

    # No local/other reference to `task` is kept beyond this point other
    # than the module's own tracking set -- force a collection cycle while
    # the task is still genuinely in flight.
    gc.collect()
    assert task in api_module._background_tasks
    assert not task.done()

    release.set()
    result = await task
    assert result == "done"
    # The done-callback must have removed it once finished.
    assert task not in api_module._background_tasks


@pytest.mark.asyncio
async def test_tracked_task_is_discarded_from_the_set_after_completion():
    task = api_module._track_background_task(asyncio.sleep(0, result="ok"), name="test-discard")
    await task
    # Let the done-callback (scheduled via add_done_callback) actually run.
    await asyncio.sleep(0)
    assert task not in api_module._background_tasks


@pytest.mark.asyncio
async def test_a_genuine_exception_in_a_tracked_task_is_logged_not_silently_dropped(caplog):
    async def failing_work():
        raise RuntimeError("boom-for-test")

    with caplog.at_level("ERROR", logger="orca.serve"):
        task = api_module._track_background_task(failing_work(), name="test-failure")
        with pytest.raises(RuntimeError):
            await task
        await asyncio.sleep(0)  # let the done-callback run

    assert task not in api_module._background_tasks
    assert any("test-failure" in r.message and "failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_a_cancelled_tracked_task_does_not_log_a_spurious_error(caplog):
    async def never_finishes():
        await asyncio.Event().wait()

    with caplog.at_level("ERROR", logger="orca.serve"):
        task = api_module._track_background_task(never_finishes(), name="test-cancel")
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0)

    assert task not in api_module._background_tasks
    assert not any("test-cancel" in r.message for r in caplog.records)
