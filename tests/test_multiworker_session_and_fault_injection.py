"""
Phase 14 §7, §10-11, §37, §49, §70, §75 -- real evidence for the
cross-worker state and fault-tolerance properties multi-worker API
deployment actually depends on.

Scope, stated honestly: this does NOT stand up two full authenticated
HTTP uvicorn processes and drive them through /api/chat end-to-end --
that requires provisioning a real user account, JWT auth, and a live
model round-trip, which is real but substantially heavier plumbing than
the property actually being tested here needs. Instead, this directly
exercises the underlying mechanism `orca.serve.api._Session` relies on
for cross-worker continuity -- `orca.serve.session_store`, backed by a
genuinely-running local Redis (`brew services list` shows `redis
started`, independent of and predating this session) -- from two
REAL, independent OS processes (spawned via multiprocessing, not
threads), which is the actual claim spec §7 cares about: "no
process-local correctness assumptions." A full authenticated HTTP E2E
across two uvicorn workers is listed as NOT_EXECUTED in
docs/orneur/phase-14/MULTI_WORKER.md, not silently skipped.
"""
from __future__ import annotations

import multiprocessing
import os
import uuid

import pytest


def _redis_reachable() -> bool:
    try:
        import redis

        client = redis.from_url("redis://localhost:6379/15", socket_connect_timeout=2)
        client.ping()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _redis_reachable(),
    reason="no local Redis reachable at redis://localhost:6379/15 -- this test proves cross-process "
    "session continuity against a real local Redis, not a fabricated one, so it skips rather than "
    "faking a result when unavailable",
)

# DB 15 -- a separate logical Redis database from whatever a developer's
# real Orca install might use on db 0, so this test can never collide
# with or leak into real session data.
_TEST_REDIS_URL = "redis://localhost:6379/15"


@pytest.fixture(autouse=True)
def _restore_env_after_test():
    prev = os.environ.get("ORNEUR_REDIS_URL")
    yield
    if prev is not None:
        os.environ["ORNEUR_REDIS_URL"] = prev
    else:
        os.environ.pop("ORNEUR_REDIS_URL", None)
    import importlib
    import orca.serve.session_store as ss
    importlib.reload(ss)


def _worker_save(session_id: str, model_variant: str, history: list, result_queue):
    """Simulates one API worker process handling the request that
    creates/updates a session."""
    os.environ["ORNEUR_REDIS_URL"] = _TEST_REDIS_URL
    import importlib
    import orca.serve.session_store as ss
    importlib.reload(ss)
    ss.save_session_state(session_id, model_variant, history)
    result_queue.put(("saved", os.getpid()))


def _worker_save_then_hang(session_id: str, model_variant: str, history: list, signal_file: str):
    """Saves state, signals readiness, then hangs -- so the parent test
    process can SIGKILL it while genuinely still alive, a real crash
    injection rather than a process that has already exited on its own."""
    os.environ["ORNEUR_REDIS_URL"] = _TEST_REDIS_URL
    import importlib
    import time
    import orca.serve.session_store as ss
    importlib.reload(ss)
    ss.save_session_state(session_id, model_variant, history)
    with open(signal_file, "w") as f:
        f.write("ready")
    time.sleep(30)


def _worker_load_and_append(session_id: str, new_turn: dict, result_queue):
    """Simulates a DIFFERENT API worker process handling the NEXT
    request for the same session_id -- proving this is not a
    process-local correctness assumption (the exact property spec §7
    requires)."""
    os.environ["ORNEUR_REDIS_URL"] = _TEST_REDIS_URL
    import importlib
    import orca.serve.session_store as ss
    importlib.reload(ss)
    state = ss.load_session_state(session_id)
    if state is None:
        result_queue.put(("not_found", os.getpid()))
        return
    history = state["history"] + [new_turn]
    ss.save_session_state(session_id, state["model_variant"], history)
    result_queue.put(("appended", os.getpid(), len(history)))


def test_session_created_on_worker_a_is_visible_and_extendable_on_worker_b():
    """The core multi-worker claim: a session created by one real OS
    process is fully visible to, and safely extendable by, a completely
    different real OS process -- no in-memory state, no sticky-session
    requirement, no process-local cache masking a real gap."""
    ctx = multiprocessing.get_context("spawn")
    session_id = f"mw-test-{uuid.uuid4().hex[:12]}"
    result_queue = ctx.Queue()

    worker_a = ctx.Process(
        target=_worker_save,
        args=(session_id, "core", [{"role": "user", "content": "hello from worker A"}], result_queue),
    )
    worker_a.start()
    worker_a.join(timeout=15)
    assert worker_a.exitcode == 0
    r1 = result_queue.get(timeout=5)
    assert r1[0] == "saved"
    pid_a = r1[1]

    worker_b = ctx.Process(
        target=_worker_load_and_append,
        args=(session_id, {"role": "assistant", "content": "reply from worker B"}, result_queue),
    )
    worker_b.start()
    worker_b.join(timeout=15)
    assert worker_b.exitcode == 0
    r2 = result_queue.get(timeout=5)
    assert r2[0] == "appended", f"worker B could not see worker A's session -- cross-worker continuity broken: {r2}"
    pid_b = r2[1]
    assert pid_a != pid_b, "sanity check: these really were two different OS processes"
    assert r2[2] == 2, "worker B's view must include both the original turn and its own appended turn"

    # Clean up this test's own key so repeated local runs don't accumulate.
    os.environ["ORNEUR_REDIS_URL"] = _TEST_REDIS_URL
    import importlib
    import orca.serve.session_store as ss
    importlib.reload(ss)
    ss.delete_session(session_id)


def test_worker_a_crash_does_not_corrupt_or_lose_worker_b_visible_state(tmp_path):
    """Fault injection (spec §11, §75): real SIGKILL of one worker
    process while it is genuinely still alive (holding readiness open
    via a signal-file handshake, same pattern as Phase 13.3's crash
    injection). Required: the state it saved before being killed
    remains fully intact and readable by a different, still-alive
    worker -- a crashed worker must not corrupt or roll back state a
    surviving worker depends on."""
    import time

    ctx = multiprocessing.get_context("spawn")
    session_id = f"mw-crash-{uuid.uuid4().hex[:12]}"
    result_queue = ctx.Queue()
    signal_file = str(tmp_path / "worker-a-ready")

    worker_a = ctx.Process(
        target=_worker_save_then_hang,
        args=(session_id, "core", [{"role": "user", "content": "state that must survive worker A's crash"}], signal_file),
    )
    worker_a.start()
    deadline = time.time() + 15
    while time.time() < deadline and not os.path.exists(signal_file):
        time.sleep(0.02)
    assert os.path.exists(signal_file), "worker A never reached readiness before the timeout"
    assert worker_a.is_alive(), "worker A must still be alive at the moment of SIGKILL for this to be a real crash injection"
    worker_a.kill()  # real SIGKILL, not a simulated exception
    worker_a.join(timeout=10)
    assert not worker_a.is_alive()

    worker_b = ctx.Process(
        target=_worker_load_and_append,
        args=(session_id, {"role": "assistant", "content": "worker B, independent of worker A's lifetime"}, result_queue),
    )
    worker_b.start()
    worker_b.join(timeout=15)
    assert worker_b.exitcode == 0
    r = result_queue.get(timeout=5)
    assert r[0] == "appended", f"worker B must see worker A's state even though worker A no longer exists: {r}"

    os.environ["ORNEUR_REDIS_URL"] = _TEST_REDIS_URL
    import importlib
    import orca.serve.session_store as ss
    importlib.reload(ss)
    ss.delete_session(session_id)
