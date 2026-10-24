"""Generation records change under one file lock.

These tests use separate threads and interpreters. An in-process flag
is not the worker boundary.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from orca.serve import generations
from tests.test_g006_tenant_isolation import client  # noqa: F401


@pytest.fixture
def home(tmp_path, monkeypatch):
    import orca.brain.memory as mem

    monkeypatch.setattr(mem, "MEMORY_DIR", tmp_path)
    generations.publish_fault = None
    yield tmp_path
    generations.publish_fault = None


def _begin(session_id: str = "sess-a", **kwargs):
    return generations.begin(
        session_id=session_id,
        user_id=None,
        delivery="upstream",
        cancellable=True,
        **kwargs,
    )


def test_heartbeat_cannot_erase_a_cancel(home):
    record, _created = _begin()
    generation_id = record["generation_id"]
    stop = threading.Event()

    def beat():
        while not stop.is_set():
            generations.touch(generation_id)

    threads = [threading.Thread(target=beat) for _ in range(4)]
    for thread in threads:
        thread.start()
    for _ in range(20):
        generations.request_cancel(generation_id)
    time.sleep(0.05)
    stop.set()
    for thread in threads:
        thread.join()
    stored = generations.read(generation_id)
    assert stored["cancel_requested"] is True
    assert stored["state"] == "running"
    view = generations.request_cancel(generation_id)
    assert view["state"] == "running"
    assert view["cancel_accepted"] is True
    assert generations.public(stored)["state"] != "cancelled"


def test_cancel_and_complete_leave_one_terminal_state(home):
    record, _created = _begin()
    generation_id = record["generation_id"]
    barrier = threading.Barrier(2)

    def complete():
        barrier.wait()
        generations.finish(generation_id, "completed", reason="done")

    def cancel():
        barrier.wait()
        generations.request_cancel(generation_id)
        generations.finish(generation_id, "cancelled", reason="cancel_requested")

    threads = [threading.Thread(target=complete), threading.Thread(target=cancel)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    stored = generations.read(generation_id)
    assert stored["state"] in {"completed", "cancelled"}
    again = generations.finish(
        generation_id,
        "completed" if stored["state"] == "cancelled" else "cancelled",
        reason="late",
    )
    assert again["state"] == stored["state"]
    view = generations.public(again)
    assert view["state"] == stored["state"]
    assert view["retry_eligible"] is (stored["state"] == "cancelled")


def test_duplicate_cancels_agree(home):
    record, _created = _begin()
    generation_id = record["generation_id"]
    views = []
    barrier = threading.Barrier(8)

    def cancel():
        barrier.wait()
        views.append(generations.request_cancel(generation_id))

    threads = [threading.Thread(target=cancel) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert all(view["cancel_accepted"] is True and view["state"] == "running" for view in views)
    assert generations.read(generation_id)["state"] == "running"


def test_two_processes_cannot_lose_the_cancel_flag(home):
    record, _created = _begin()
    generation_id = record["generation_id"]
    script = textwrap.dedent(f"""
    import orca.brain.memory as mem
    from pathlib import Path
    mem.MEMORY_DIR = Path({str(home)!r})
    from orca.serve import generations
    generations.request_cancel({generation_id!r})
    for _ in range(100):
        generations.touch({generation_id!r})
    stored = generations.read({generation_id!r})
    assert stored["cancel_requested"] is True
    assert stored["state"] == "running"
    print("ok")
    """)
    first = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=False)
    second = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=False)
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert "ok" in first.stdout and "ok" in second.stdout
    assert generations.read(generation_id)["cancel_requested"] is True


def test_crash_during_publication_reuses_the_reserved_id(home):
    generations.publish_fault = "after-idempotency-reserve"
    with pytest.raises(RuntimeError, match="publication interrupted"):
        _begin(idempotency_key="same-key-1", request_hash="a" * 64)
    generations.publish_fault = None
    record, created = _begin(idempotency_key="same-key-1", request_hash="a" * 64)
    assert created is True
    again, created_again = _begin(idempotency_key="same-key-1", request_hash="a" * 64)
    assert created_again is False
    assert again["generation_id"] == record["generation_id"]
    assert again["state"] == "running"


def test_live_heartbeat_survives_a_gap_longer_than_the_stale_window(home):
    record, _created = _begin()
    generation_id = record["generation_id"]
    heartbeat = generations.start_heartbeat(generation_id, interval=0.05)
    try:
        assert generations.worker_alive(generation_id) is True
        time.sleep(0.25)
        view = generations.public(generations.read(generation_id), stale_after=0.12)
        assert view["state"] == "running"
        assert view["terminal"] is False
        assert view["retry_eligible"] is False
    finally:
        heartbeat.stop()
    assert generations.worker_alive(generation_id) is False
    stale = generations.public(
        {"state": "running", "updated_at": time.time() - 1, "cancel_requested": False,
         "generation_id": generation_id, "session_id": "sess-a", "delivery": "upstream",
         "cancellable": True, "reason": None},
        stale_after=0.12,
    )
    assert stale["state"] == "interrupted_unknown"
    assert stale["retry_eligible"] is True


def test_identical_idempotency_keys_create_one_record(home):
    barrier = threading.Barrier(2)
    found = []

    def open_one():
        barrier.wait()
        record, created = _begin(idempotency_key="same-key-2", request_hash="b" * 64)
        found.append((record["generation_id"], created))

    threads = [threading.Thread(target=open_one) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len({item[0] for item in found}) == 1
    assert sorted(item[1] for item in found) == [False, True]


def test_unreadable_record_is_not_republished(home):
    record, created = _begin(idempotency_key="same-key-4", request_hash="e" * 64)
    assert created is True
    path = Path(home) / "generations" / f"{record['generation_id']}.json"
    path.write_bytes(b"{not-json")
    with pytest.raises(generations.GenerationDenied):
        _begin(idempotency_key="same-key-4", request_hash="e" * 64)
    assert path.read_bytes() == b"{not-json"


def test_heartbeat_rejects_a_path_id(home):
    with pytest.raises(generations.GenerationDenied):
        generations.start_heartbeat("../escape")
    assert generations.worker_alive("../escape") is False


def test_same_idempotency_key_rejects_a_different_body(home):
    record, created = _begin(idempotency_key="same-key-3", request_hash="c" * 64)
    assert created is True
    with pytest.raises(generations.GenerationMismatch) as raised:
        _begin(idempotency_key="same-key-3", request_hash="d" * 64)
    assert raised.value.generation_id == record["generation_id"]
    assert generations.read(record["generation_id"])["request_hash"] == "c" * 64


def test_disconnect_cancel_is_not_replaced_by_completion(home):
    record, _created = _begin()
    generation_id = record["generation_id"]
    generations.finish(generation_id, "cancelled", reason="client_disconnected")
    late = generations.finish(generation_id, "completed", reason="done")
    assert late["state"] == "cancelled"
    assert late["reason"] == "client_disconnected"
    view = generations.public(late)
    assert view["state"] == "cancelled"
    assert view["retry_eligible"] is True
    assert view["terminal"] is True


def test_terminal_state_survives_a_new_process(home):
    record, _created = _begin(session_id="sess-restart")
    generation_id = record["generation_id"]
    generations.finish(generation_id, "failed", reason="stream_failed")
    script = textwrap.dedent(f"""
    import orca.brain.memory as mem
    from pathlib import Path
    mem.MEMORY_DIR = Path({str(home)!r})
    from orca.serve import generations
    stored = generations.read({generation_id!r})
    view = generations.public(stored)
    assert stored["state"] == "failed"
    assert view["state"] == "failed"
    assert view["retry_eligible"] is True
    assert view["terminal"] is True
    print("ok")
    """)
    completed = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
    assert "ok" in completed.stdout


def test_stream_rejects_an_idempotency_key_reused_for_a_different_message(client, monkeypatch):
    from orca.serve import ratelimit
    from tests.fake_ollama import FakeOllama, point_orneur_at
    from tests.test_g006_tenant_isolation import _hdr, _signup

    ratelimit._local_counters.clear()
    with FakeOllama() as fake:
        point_orneur_at(fake, monkeypatch)
        token, _user = _signup(client)
        headers = {**_hdr(token), "Idempotency-Key": "stream-key-9"}
        first = client.post("/api/stream", json={"message": "hello there", "model_variant": "nano"}, headers=headers)
        assert first.status_code == 200, first.text
        import json
        events = [json.loads(line[6:]) for line in first.text.splitlines() if line.startswith("data: ")]
        session_id = next(event["session_id"] for event in events if event["type"] == "session")
        second = client.post(
            "/api/stream",
            json={"message": "a different question", "session_id": session_id, "model_variant": "nano"},
            headers=headers,
        )
        assert second.status_code == 422
        body = second.json()
        assert body["code"] == "idempotency_mismatch"
        assert body["generation_id"]
        assert sum(1 for request in fake.requests if request.get("stream")) == 1
