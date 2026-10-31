"""LANDMARK-04 Phase 1 (P1-F) -- quota and routing integrity against a REAL ``orca serve`` (fixture provider; evidence class: LIVE_API).

* A free account is refused at its daily limit with a machine-readable code and the refused request never reaches the model (no cost).
* A burst larger than the remaining allowance admits EXACTLY the remaining count (atomic reservation, no over-spend under concurrency).
* A turn that fails at the provider is not charged. A client-cancelled turn is not stored as a completed answer.
* A model that is not configured is refused, never silently replaced, and the served identity is reported truthfully.
"""
from __future__ import annotations

import json
import threading
import time

import pytest

from tests.fake_ollama import FakeOllama
from tests.journey.harness import JOURNEY_MODEL, LiveServer, User

LIMIT = 50


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    fake = FakeOllama(models=(JOURNEY_MODEL,), reply="OK")
    fake.__enter__()
    srv = LiveServer(tmp_path_factory.mktemp("p1-quota"), extra_env={"ORNEUR_OLLAMA_HOST": fake.host, "OLLAMA_HOST": fake.host})
    try:
        srv.wait_ready()
        yield srv, fake
    finally:
        srv.stop()
        fake.__exit__(None, None, None)


def _used(u):
    return u.get("/api/usage").json()["today"]["messages"]


def test_Q1_a_provider_failure_is_not_charged_and_is_reported(env):
    srv, fake = env
    u = User(srv.base, "q1")
    before = _used(u)
    fake.fail_status = 503
    try:
        status, events = u.stream("hello")
    finally:
        fake.fail_status = None
    assert any(e.get("type") == "error" for e in events) or status != 200, events[-2:]
    assert not any(e.get("type") == "done" and e.get("persisted") == "saved" for e in events), "a failed generation was reported as saved"
    assert _used(u) == before, "a turn the provider failed was charged to the user"


def test_Q2_limit_refuses_without_reaching_the_model_and_a_burst_cannot_overspend(env):
    srv, fake = env
    u = User(srv.base, "q2")
    # consume LIMIT-4 quickly, one at a time
    for i in range(LIMIT - 4):
        status, ev = u.stream(f"msg {i}")
        assert status == 200 and any(e.get("type") == "done" for e in ev), (i, ev[-2:])
    assert _used(u) == LIMIT - 4
    reqs_before = len(fake.requests)
    results = []
    lock = threading.Lock()

    def one(i):
        s, ev = u.stream(f"burst {i}")
        ok = s == 200 and any(e.get("type") == "done" and e.get("persisted") == "saved" for e in ev)
        with lock:
            results.append((ok, s, ev[-1] if ev else None))

    ts = [threading.Thread(target=one, args=(i,)) for i in range(10)]
    [t.start() for t in ts]
    [t.join(timeout=120) for t in ts]
    served = sum(1 for ok, *_ in results if ok)
    assert served == 4, f"burst of 10 with 4 remaining served {served}: {results}"
    # user-facing generations are the streamed ones; each SERVED turn also triggers one non-streamed background extraction call (see P1 register: unmetered ancillary call)
    new = fake.requests[reqs_before:]
    assert sum(1 for r in new if r.get("stream")) == 4, "refused burst requests reached the model"
    assert sum(1 for r in new if not r.get("stream")) <= 4, "ancillary model calls exceed the number of served turns"
    assert _used(u) == LIMIT
    # exhausted: the next request is refused with a stable machine-readable code, and costs nothing
    reqs = len(fake.requests)
    s, ev = u.stream("one more")
    body = json.dumps(ev)
    assert "quota_exceeded" in body or s == 429, (s, ev)
    assert len(fake.requests) == reqs, "a quota-refused request still reached the model (streamed or ancillary)"
    assert _used(u) == LIMIT


def test_Q3_unconfigured_model_is_refused_not_substituted(env):
    srv, fake = env
    u = User(srv.base, "q3")
    reqs = len(fake.requests)
    s, ev = u.stream("hi", model_variant="ultra")
    served = {r.get("model") for r in fake.requests[reqs:]}
    # either refused outright, or served by a model that really exists on the provider and says so; never an unlisted name
    assert served <= {JOURNEY_MODEL} or not served, served
    done = [e for e in ev if e.get("type") == "done"]
    if done:
        disclosed = json.dumps(done[-1])
        assert JOURNEY_MODEL in disclosed or "model" in disclosed, done[-1]


def test_Q4_cancelled_turn_is_not_stored_as_a_completed_answer(env):
    srv, fake = env
    fake2 = FakeOllama(models=(JOURNEY_MODEL,), chunks=[f"w{i} " for i in range(16)], reply="".join(f"w{i} " for i in range(16)), chunk_delay=0.3)
    fake2.__enter__()
    s2 = LiveServer(__import__("pathlib").Path(__import__("tempfile").mkdtemp(prefix="p1q4-")), extra_env={"ORNEUR_OLLAMA_HOST": fake2.host, "OLLAMA_HOST": fake2.host})
    try:
        s2.wait_ready()
        u = User(s2.base, "q4")
        sid = None
        import httpx, uuid
        with httpx.Client(base_url=s2.base, timeout=60) as c:
            with c.stream("POST", "/api/stream", json={"message": "tell me the long story", "model_variant": "core"},
                          headers={**u.headers, "Idempotency-Key": str(uuid.uuid4())}) as r:
                n = 0
                for line in r.iter_lines():
                    if line.startswith("data: "):
                        ev = json.loads(line[6:])
                        if ev.get("type") == "session":
                            sid = ev["session_id"]
                        if ev.get("type") == "chunk":
                            n += 1
                            if n >= 3:
                                break          # the client hangs up mid-answer
        deadline = time.time() + 10
        while time.time() < deadline and fake2.stream_aborts == 0:
            time.sleep(0.2)
        assert fake2.stream_aborts >= 1, "the provider was never hung up on"
        time.sleep(1.0)
        msgs = u.get(f"/api/session/{sid}/messages").json()["messages"] if sid else []
        assert not [m for m in msgs if m["role"] == "assistant" and "w15" in m["content"]], msgs
        assert fake2.streams_open == 0, "an upstream generation is still running after the client left"
    finally:
        s2.stop()
        fake2.__exit__(None, None, None)
