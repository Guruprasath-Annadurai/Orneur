"""Phase 15.5 -- orca.mission.executor unit tests (no DB required)."""
from __future__ import annotations

import threading

import pytest

from orca.mission.executor import ExecutionFailed, RecordingTestExecutor


def test_records_invocation():
    ex = RecordingTestExecutor()
    result = ex.execute(operation_id="op_1", kind="deploy", mission_id="mis_1")
    assert result == "test-result:op_1"
    assert ex.call_count == 1
    assert ex.invocations[0] == {"operation_id": "op_1", "kind": "deploy", "mission_id": "mis_1"}


def test_fail_next_raises_once():
    ex = RecordingTestExecutor(fail_next=True)
    with pytest.raises(ExecutionFailed):
        ex.execute(operation_id="op_1", kind="deploy", mission_id=None)
    assert ex.call_count == 1  # the failed attempt still counts as an invocation
    # fail_next resets -- next call succeeds
    result = ex.execute(operation_id="op_1", kind="deploy", mission_id=None)
    assert result == "test-result:op_1"
    assert ex.call_count == 2


def test_thread_safe_call_count():
    ex = RecordingTestExecutor()

    def _call():
        ex.execute(operation_id="op_concurrent", kind="deploy", mission_id=None)

    threads = [threading.Thread(target=_call) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    assert ex.call_count == 20
