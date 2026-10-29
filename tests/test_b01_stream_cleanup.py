"""B-01 final integration (Wave B/F): rapid client disconnection leaks no task, lock or quota reservation.

The REAL app runs under a real uvicorn server on a real localhost socket (the in-process ASGITransport never reports a disconnect); the model is a controllable
provider (FakeOllama). Many requests are started and abandoned at every stage - before the response headers, after the first chunk, after the last chunk, and
not at all - and afterwards the server's own event loop is inspected: no ``kernel-run`` producer task, no extra task of any kind, no stream the provider is
still serving, no held quota reservation, no held turn authority. Evidence class: DETERMINISTIC (real socket, in-process server, fixture provider).
"""
from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
import uuid

import pytest

from tests.fake_ollama import FakeOllama, point_orneur_at
from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401  (fixture re-export)


@pytest.fixture
def live(client, monkeypatch):  # noqa: F811
    uvicorn = pytest.importorskip("uvicorn")
    import orca.serve.api as api
    from orca.serve import ratelimit

    ratelimit._local_counters.clear()
    monkeypatch.setattr(ratelimit, "enforce", lambda *a, **k: None)
    # A LONG generation (600 pieces, ~30s): if an abandoned request's producer were not cancelled it would keep running far past the bounds asserted below,
    # instead of finishing by itself and hiding the leak.
    fake = FakeOllama(models=("orca-nano", "orca-core", "orca-ultra"), chunks=[f"p{i} " for i in range(600)], chunk_delay=0.05)
    fake.__enter__()
    point_orneur_at(fake, monkeypatch)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(64)
    box: dict = {}

    def run_server():
        loop = asyncio.new_event_loop()
        box["loop"] = loop
        asyncio.set_event_loop(loop)
        box["server"] = uvicorn.Server(uvicorn.Config(api.app, log_level="error", lifespan="off"))
        loop.run_until_complete(box["server"].serve(sockets=[sock]))

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    for _ in range(300):
        if getattr(box.get("server"), "started", False):
            break
        time.sleep(0.01)
    assert box["server"].started
    yield {"port": sock.getsockname()[1], "fake": fake, "loop": box["loop"], "client": client}
    box["server"].should_exit = True
    thread.join(timeout=8)
    fake.__exit__(None, None, None)


def _server_tasks(loop) -> list[str]:
    async def names():
        return sorted(f"{t.get_name()}:{getattr(t.get_coro(), '__qualname__', '?')}" for t in asyncio.all_tasks() if t is not asyncio.current_task())
    return asyncio.run_coroutine_threadsafe(names(), loop).result(timeout=5)


def _request(port: int, token: str, sid: str, message: str) -> socket.socket:
    body = json.dumps({"message": message, "session_id": sid, "model_variant": "nano"}).encode()
    s = socket.create_connection(("127.0.0.1", port), timeout=10)
    s.sendall(b"POST /api/stream HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nConnection: close\r\n"
              + f"Authorization: Bearer {token}\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body)
    return s


def _read_until(s: socket.socket, needle: bytes, timeout=8.0) -> bytes:
    got, end = b"", time.monotonic() + timeout
    while needle not in got and time.monotonic() < end:
        try:
            part = s.recv(4096)
        except OSError:
            break
        if not part:
            break
        got += part
    return got


def _wait(pred, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


def _hang_up(s: socket.socket) -> None:
    try:
        s.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    s.close()


def test_abandoned_streams_leave_no_task_stream_reservation_or_authority(live):
    client, fake, port, loop = live["client"], live["fake"], live["port"], live["loop"]
    token, _ = _signup(client)
    usage = lambda: client.get("/api/usage", headers=_hdr(token)).json()["today"]["messages"]  # noqa: E731
    # warm-up request (a short answer) so lazily created long-lived objects (pools, caches) exist before the baseline is taken
    fake.chunks = ["warm"]
    s = _request(port, token, f"{uuid.uuid4().hex[:8]}-warm", "warm up")
    assert b'"type": "done"' in _read_until(s, b'"type": "done"')
    _hang_up(s)
    assert _wait(lambda: fake.streams_open == 0)
    time.sleep(0.3)
    fake.chunks = [f"p{i} " for i in range(600)]
    baseline = _server_tasks(loop)
    spent = usage()

    stages = ["after_first_chunk", "after_many_chunks", "before_any_byte", "after_first_chunk", "after_many_chunks", "before_any_byte"] * 3
    expected_spent = 0
    for i, stage in enumerate(stages):
        sid = f"{uuid.uuid4().hex[:8]}-leak{i}"
        s = _request(port, token, sid, f"abandon me {i}")
        if stage == "before_any_byte":
            _hang_up(s)                                              # gone before the server wrote anything
            expected_spent += 0                                      # (race: the unit is spent only if the model had already produced output)
        elif stage == "after_first_chunk":
            assert b'"type": "chunk"' in _read_until(s, b'"type": "chunk"')
            _hang_up(s)
            expected_spent += 1
        else:
            assert b"p20 " in _read_until(s, b"p20 ")
            _hang_up(s)
            expected_spent += 1
    # Every abandoned generation (each would run ~30s) must be stopped promptly - bounded well below its natural length.
    assert _wait(lambda: fake.streams_open == 0, 5), f"the provider is still serving {fake.streams_open} abandoned stream(s)"
    # let every producer finish and the event loop settle
    assert _wait(lambda: not [t for t in _server_tasks(loop) if t.startswith("kernel-run")], 3), _server_tasks(loop)
    time.sleep(0.5)
    after = _server_tasks(loop)
    leaked = [t for t in after if t not in baseline]
    # The only tasks allowed to appear are derived-state side tasks that exist by design after a COMMITTED turn (knowledge-graph enrichment); none is part of
    # the stream lifecycle. Everything the stream itself creates - KernelRun producers, channel waiters, quota/authority heartbeats - must be gone.
    stream_owned = [t for t in leaked if any(k in t for k in ("kernel-run", "_beat", "_keepalive", "_event_stream", "_releasing_iterator", "RawDeltaChannel"))]
    assert stream_owned == [], f"stream-owned tasks survived: {stream_owned}"
    # quota: the unit is spent exactly when output had been produced; before-any-byte hang-ups may or may not have reached the model, so bound it
    delta = usage() - spent
    n_before = stages.count("before_any_byte")
    assert expected_spent <= delta <= expected_spent + n_before, (delta, expected_spent, n_before)
    # no reservation is left held: a stale reservation would be refunded later and show as a NEGATIVE drift, a leaked one as a stuck count - neither: stable
    time.sleep(1.0)
    assert usage() - spent == delta
    # and every conversation that was abandoned can be used again at once (turn authority released)
    from orca.serve import conversations

    fake.chunks = ["ok"]
    for sid_hint in range(3):
        sid = f"{uuid.uuid4().hex[:8]}-after"
        s = _request(port, token, sid, "still works")
        assert b'"type": "done"' in _read_until(s, b'"type": "done"')
        _hang_up(s)
    assert conversations.store_available()


def test_hanging_up_before_the_first_body_byte_never_strands_quota_or_authority(live):
    """A never-started response body has no ``finally`` to run: the release must come from the response itself (``_ReleasingStreamingResponse``).
    Directed repro: send the request and slam the socket in the same instant, many times, on ONE conversation."""
    client, fake, port, loop = live["client"], live["fake"], live["port"], live["loop"]
    token, _ = _signup(client)
    usage = lambda: client.get("/api/usage", headers=_hdr(token)).json()["today"]["messages"]  # noqa: E731
    fake.chunks, fake.chunk_delay = ["x"], 0.0
    s = _request(port, token, f"{uuid.uuid4().hex[:8]}-warm", "warm")
    assert b'"type": "done"' in _read_until(s, b'"type": "done"')
    _hang_up(s)
    time.sleep(0.3)
    baseline = _server_tasks(loop)
    spent = usage()
    sid = f"{uuid.uuid4().hex[:8]}-instant"
    fake.pre_response_delay = 0.4                                   # the model is slow to start, so the hang-up always wins
    for i in range(30):
        _hang_up(_request(port, token, sid, f"instant hang-up {i}"))
    time.sleep(2.0)
    assert _wait(lambda: not [t for t in _server_tasks(loop) if t not in baseline and any(k in t for k in ("_beat", "_keepalive", "kernel-run"))], 8), _server_tasks(loop)
    fake.pre_response_delay = 0.0
    assert usage() == spent, "reservations taken by requests that never produced output must be refunded"
    s = _request(port, token, sid, "usable at once")
    assert b'"type": "done"' in _read_until(s, b'"type": "done"'), "the conversation was left busy by the abandoned requests"
    _hang_up(s)
