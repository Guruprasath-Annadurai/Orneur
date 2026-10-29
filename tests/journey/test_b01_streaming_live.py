"""B-01 final integration -- the default chat path streams REAL upstream deltas (evidence class: LIVE_API + FIXTURE provider).

A real ``orca serve`` process (the canonical entry point) talks over real HTTP to a controllable provider whose chunks are written with measurable gaps.
Everything ORNEUR-side -- auth, quota, authority, the Cognitive Kernel, the ModelGateway, DLP, SQLite -- is the real code. What is asserted is never what a model
says, but WHEN bytes arrive, what the provider was sent, whether its connection was closed, and what is in the stores.

Run:  pytest tests/journey/test_b01_streaming_live.py -p no:cacheprovider -v
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

import httpx
import pytest

from tests.fake_ollama import FakeOllama
from tests.journey.harness import JOURNEY_MODEL, LiveServer, User

SECRET = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2"
AWS = "AKIAIOSFODNN7EXAMPLE"
GH = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3"
BEARER = "Bearer " + "eyJhbGciOiJIUzI1NiJ9abcdefghijkl"
PEM = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEAxyz0123456789\n-----END RSA PRIVATE KEY-----"
LEAKS = (SECRET, AWS, GH, "eyJhbGciOiJIUzI1NiJ9abcdefghijkl", "MIIEowIBAAKCAQEAxyz0123456789")


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    fake = FakeOllama(models=(JOURNEY_MODEL,))
    fake.__enter__()
    home = tmp_path_factory.mktemp("b01-stream-home")
    srv = LiveServer(home, extra_env={"ORNEUR_OLLAMA_HOST": fake.host, "OLLAMA_HOST": fake.host})
    try:
        srv.wait_ready()
        yield {"srv": srv, "fake": fake, "home": home, "user": User(srv.base, "b01")}      # one account: sign-ups are rate limited per IP
    finally:
        srv.stop()
        fake.__exit__(None, None, None)


@pytest.fixture
def env(stack):
    fake: FakeOllama = stack["fake"]
    fake.fail_status, fake.truncate_after, fake.pre_response_delay, fake.malformed = None, None, 0.0, False
    fake.chunk_delay = 0.0
    fake.reply = "FAKE-REPLY"
    fake._chunks = None
    fake.chunk_times.clear()
    fake.stream_aborted.clear()
    fake.stream_started.clear()
    fake.chunks_sent, fake.streams_finished = 0, 0
    return stack


def _usage(user: User) -> int:
    return user.get("/api/usage").json()["today"]["messages"]


def run_stream(user: User, message: str, session_id: str | None = None, *, stop_after_chunks: int | None = None, stop_after_s: float | None = None,
               token: str | None = None, key: str | None = None, **extra):
    """POST /api/stream as conversation.html does, recording when every SSE event ARRIVED. Returns (status, events)."""
    headers = {"Authorization": f"Bearer {token or user.token}", "Idempotency-Key": key or str(uuid.uuid4())}
    body = {"message": message, "session_id": session_id, "model_variant": "core", **extra}
    events, t0, chunks = [], time.monotonic(), 0
    with user.http.stream("POST", "/api/stream", json=body, headers=headers) as resp:
        if resp.status_code != 200 or "text/event-stream" not in resp.headers.get("content-type", ""):
            resp.read()
            return resp.status_code, [{"type": "http_body", "body": resp.text[:300]}]
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            ev = json.loads(line[6:])
            ev["_t"] = time.monotonic() - t0
            ev["_abs"] = time.monotonic()
            events.append(ev)
            chunks += ev.get("type") == "chunk"
            if (stop_after_chunks and chunks >= stop_after_chunks) or (stop_after_s is not None and ev["_t"] >= stop_after_s):
                break                                   # leaving the `with` closes the connection: exactly what the browser's Stop does
    return 200, events


def wait_until(predicate, timeout=8.0, step=0.05):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(step)
    return predicate()


def transcript(user: User, sid: str) -> list[tuple[str, str]]:
    r = user.get(f"/api/session/{sid}/messages")
    assert r.status_code == 200, r.text
    return [(m["role"], m["content"]) for m in r.json()["messages"]]


def answering_requests(fake: FakeOllama, prompt: str) -> list[dict]:
    """The provider requests that ANSWER ``prompt`` (final message == prompt). Side calls - e.g. knowledge-graph extraction, which arrives
    asynchronously and quotes earlier turns - are excluded, so a context assertion cannot pass or fail for the wrong reason."""
    return [r for r in fake.requests if (r.get("messages") or [{}])[-1].get("content", "").strip() == prompt.strip()]


def answering_calls(fake: FakeOllama, prompt: str) -> int:
    return len(answering_requests(fake, prompt))


# ---- S1 / S8: the default path delivers upstream deltas as they are generated ------------------------------------------------------------------------

def test_S1_default_chat_delivers_real_upstream_deltas_before_generation_ends(env):
    fake, user = env["fake"], env["user"]
    pieces = [f"word{i} " for i in range(8)]
    fake.chunks, fake.chunk_delay = pieces, 0.35
    sid = str(uuid.uuid4())
    seen_at_first_chunk = {}
    t_start = time.monotonic()
    headers = {"Authorization": f"Bearer {user.token}", "Idempotency-Key": str(uuid.uuid4())}
    events = []
    with user.http.stream("POST", "/api/stream", json={"message": "tell me a long story", "session_id": sid, "model_variant": "core"}, headers=headers) as resp:
        assert resp.status_code == 200
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            ev = json.loads(line[6:])
            ev["_t"] = time.monotonic() - t_start
            events.append(ev)
            if ev["type"] == "chunk" and not seen_at_first_chunk:
                seen_at_first_chunk = {"sent": fake.chunks_sent, "finished": fake.streams_finished}
    types = [e["type"] for e in events]
    chunks = [e for e in events if e["type"] == "chunk"]
    assert len(chunks) >= 3, types
    # The first chunk reached the client while the provider was still generating (it had written fewer than all pieces and had not finished).
    assert seen_at_first_chunk["sent"] < len(pieces) and seen_at_first_chunk["finished"] == 0, seen_at_first_chunk
    # Truthful labelling: an upstream, cancellable stream is announced before its first chunk; nothing here is a replay.
    stream_ev = next(e for e in events if e["type"] == "stream")
    assert stream_ev["delivery"] == "upstream" and stream_ev["cancellable"] is True
    assert types.index("stream") < types.index("chunk") < types.index("done")
    assert not any(e.get("replayed") for e in events)
    done = events[-1]
    assert done["type"] == "done" and done["delivery"] == "upstream" and done["persisted"] == "saved"
    # The chunk arrivals track the provider's own writes: no buffering between the provider and the browser.
    gaps = [b["_t"] - a["_t"] for a, b in zip(chunks, chunks[1:])]
    assert sum(g > 0.15 for g in gaps) >= len(gaps) - 1, f"chunks arrived in a burst, not progressively: {gaps}"
    assert chunks[-1]["_t"] - chunks[0]["_t"] >= 0.35 * (len(pieces) - 2)
    # Exactly the generated text, once: no mega-chunk repeating the answer, stored == shown.
    shown = "".join(c["text"] for c in chunks)
    assert shown == "".join(pieces)
    assert transcript(user, sid)[-1] == ("assistant", shown)
    assert "response" not in done and shown not in json.dumps({k: v for k, v in done.items() if k != "sources"})
    # The model event names what the gateway actually resolved, and the done event confirms the same identity.
    model_ev = next(e for e in events if e["type"] == "model")
    assert model_ev["identity"] == done["model_identity"] and model_ev["identity"].get("served_model")


def test_S8_one_plain_chat_request_is_one_answering_dispatch_and_one_unit(env):
    fake, user = env["fake"], env["user"]
    fake.chunks, fake.chunk_delay = ["alpha ", "beta ", "gamma"], 0.05
    before, used = answering_calls(fake, "count the model calls"), _usage(user)
    status, events = run_stream(user, "count the model calls", str(uuid.uuid4()))
    assert status == 200 and events[-1]["type"] == "done"
    wait_until(lambda: answering_calls(fake, "count the model calls") > before)
    time.sleep(0.5)                                      # a duplicated dispatch would have arrived by now
    assert answering_calls(fake, "count the model calls") - before == 1, "plain chat must make exactly one answering model call"
    assert _usage(user) - used == 1, "and spend exactly one unit"


def test_S11_the_non_streaming_chat_route_is_unchanged(env):
    fake, user = env["fake"], env["user"]
    fake.reply = "A complete JSON answer"
    r = user.post("/api/chat", json={"message": "hello", "session_id": str(uuid.uuid4()), "model_variant": "core"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["response"] == "A complete JSON answer" and body["persisted"] == "saved"
    # /api/chat never asks the provider to stream.
    assert fake.requests[-1].get("stream") is False or "stream" not in fake.requests[-1] or fake.requests[-1]["stream"] is False


# ---- S4 / S5 / S6 / S7: Stop ------------------------------------------------------------------------------------------------------------------------

def test_S4_S5_S6_S7_stop_cancels_the_provider_frees_the_conversation_and_leaves_no_phantom_turn(env):
    fake, user = env["fake"], env["user"]
    pieces = [f"tok{i} " for i in range(40)]
    fake.chunks, fake.chunk_delay = pieces, 0.2
    sid = str(uuid.uuid4())
    used = _usage(user)
    status, events = run_stream(user, "write something very long", sid, stop_after_chunks=3)
    assert status == 200 and sum(e["type"] == "chunk" for e in events) == 3 and not any(e["type"] == "done" for e in events)
    # S4: the PROVIDER's generation really stopped (its socket was closed), long before it would have finished all 40 pieces.
    assert wait_until(lambda: fake.stream_aborted.is_set()), "the provider was never told to stop"
    assert wait_until(lambda: fake.streams_open == 0)
    sent_at_stop = fake.chunks_sent
    time.sleep(0.8)
    assert fake.chunks_sent == sent_at_stop and fake.chunks_sent < len(pieces) and fake.streams_finished == 0
    # S6: no phantom turn -- the cancelled generation is not in the transcript, so it cannot contaminate the next prompt.
    assert transcript(user, sid) == []
    # S7: the first model output had arrived, so the unit is spent once (the established billing policy; not refunded after output).
    assert _usage(user) - used == 1
    # S5: the very next turn on the SAME conversation is admitted immediately (authority was released, nothing is stuck busy).
    fake.chunks, fake.chunk_delay = ["second ", "answer"], 0.0
    status, events2 = run_stream(user, "and now a short one", sid)
    assert status == 200 and events2[-1]["type"] == "done" and events2[-1]["persisted"] == "saved", events2[-3:]
    assert transcript(user, sid) == [("user", "and now a short one"), ("assistant", "second answer")]
    # ...and its prompt to the model carries only committed history -- never the abandoned partial reply.
    ctx = json.dumps(answering_requests(fake, "and now a short one")[-1]["messages"])
    assert "tok0" not in ctx and "tok1" not in ctx and "write something very long" not in ctx


def test_S7_stop_before_any_output_refunds_the_unit(env):
    fake, user = env["fake"], env["user"]
    fake.pre_response_delay, fake.chunks = 3.0, ["never ", "seen"]
    used = _usage(user)
    sid = str(uuid.uuid4())
    # The provider holds the request for 3s before producing a token; the client leaves after 0.8s.
    headers = {"Authorization": f"Bearer {user.token}", "Idempotency-Key": str(uuid.uuid4())}
    with pytest.raises(httpx.ReadTimeout):
        with httpx.Client(base_url=user.base, timeout=httpx.Timeout(0.8, connect=5)) as c:
            with c.stream("POST", "/api/stream", json={"message": "slow start", "session_id": sid, "model_variant": "core"}, headers=headers) as r:
                for _ in r.iter_lines():
                    pass
    assert wait_until(lambda: _usage(user) == used, timeout=8), "a request cancelled before the model produced anything must not spend quota"
    fake.pre_response_delay = 0.0
    assert transcript(user, sid) == []
    status, events = run_stream(user, "now answer", sid)                       # the conversation is free again
    assert status == 200 and events[-1]["type"] == "done"


def test_S7_provider_failure_before_output_refunds_and_reports(env):
    fake, user = env["fake"], env["user"]
    fake.fail_status = 500
    used, sid = _usage(user), str(uuid.uuid4())
    status, events = run_stream(user, "this will fail", sid)
    assert status == 200 and events[-1]["type"] == "error" and not any(e["type"] in ("chunk", "done") for e in events)
    assert _usage(user) == used and transcript(user, sid) == []


def test_S6_provider_dying_mid_stream_is_an_error_not_a_completed_turn(env):
    fake, user = env["fake"], env["user"]
    fake.chunks, fake.chunk_delay, fake.truncate_after = ["one ", "two ", "three ", "four "], 0.05, 2
    used, sid = _usage(user), str(uuid.uuid4())
    status, events = run_stream(user, "die halfway", sid)
    assert status == 200 and events[-1]["type"] == "error", [e["type"] for e in events]
    assert not any(e["type"] == "done" for e in events)
    assert transcript(user, sid) == [], "a truncated generation must not be stored as an answer"
    assert _usage(user) - used == 1, "output was produced before the failure, so the unit stays spent (established policy)"
    # and the conversation recovers
    fake.truncate_after, fake.chunks, fake.chunk_delay = None, ["recovered"], 0.0
    status, events = run_stream(user, "try again", sid)
    assert events[-1]["type"] == "done" and transcript(user, sid)[-1] == ("assistant", "recovered")


def test_S6_stop_then_new_turn_never_resurrects_the_abandoned_reply_after_a_reload(env):
    fake, user = env["fake"], env["user"]
    fake.chunks, fake.chunk_delay = [f"abandoned{i} " for i in range(30)], 0.15
    sid = str(uuid.uuid4())
    run_stream(user, "first", sid, stop_after_chunks=2)
    wait_until(lambda: fake.streams_open == 0)
    fake.chunks, fake.chunk_delay = ["kept"], 0.0
    run_stream(user, "second", sid)
    rows = transcript(user, sid)
    assert rows == [("user", "second"), ("assistant", "kept")]
    export = user.get(f"/api/session/{sid}/export?format=md").text
    assert "abandoned" not in export


# ---- S3: DLP across chunk boundaries ----------------------------------------------------------------------------------------------------------------

def _all_bytes_under(home: Path) -> list[tuple[str, bytes]]:
    out = []
    for p in home.rglob("*"):
        if p.is_file():
            try:
                out.append((str(p), p.read_bytes()))
            except OSError:
                pass
    return out


@pytest.mark.parametrize("size", [1, 2, 3, 5, 8, 13])
def test_S3_secrets_split_across_chunk_sizes_never_reach_wire_store_or_next_prompt(env, size):
    fake, user = env["fake"], env["user"]
    reply = f"keys: {SECRET} and {AWS} and {GH} and {BEARER} then\n{PEM}\nend of keys"
    fake.chunks, fake.chunk_delay = [reply[i:i + size] for i in range(0, len(reply), size)], 0.0
    sid = str(uuid.uuid4())
    status, events = run_stream(user, "show me the keys", sid)
    assert status == 200 and events[-1]["type"] == "done" and events[-1]["persisted"] == "saved", events[-2:]
    wire = json.dumps(events)
    shown = "".join(e["text"] for e in events if e["type"] == "chunk")
    for leak in LEAKS:
        assert leak not in wire, f"{leak[:8]}... reached the browser (chunk size {size})"
    assert "REDACTED" in shown and shown.startswith("keys: ") and shown.rstrip().endswith("end of keys")
    rows = transcript(user, sid)
    assert rows[-1] == ("assistant", shown), "the persisted answer must be exactly the redacted text the client saw"
    export = user.get(f"/api/session/{sid}/export?format=md").text
    for leak in LEAKS:
        assert leak not in export and leak not in json.dumps(rows)
    # Later retrieved context: the next prompt to the model carries the redacted history, never the credential.
    fake.chunks = ["ok"]
    n_before = len(fake.requests)
    run_stream(user, "and what did you say before?", sid)
    time.sleep(1.0)                                         # let the asynchronous knowledge-graph side call land too
    sent = json.dumps(answering_requests(fake, "and what did you say before?")[-1]["messages"])
    assert "REDACTED" in sent
    for leak in LEAKS:
        for request in fake.requests[n_before - 1:]:        # EVERY later provider call, side calls included
            assert leak not in json.dumps(request), "the credential came back to the model through conversation history"
    # No byte of any file ORNEUR wrote (SQLite, WAL, JSONL, memory, logs) contains the credential.
    for path, data in _all_bytes_under(env["home"]):
        for leak in LEAKS:
            assert leak.encode() not in data, f"{leak[:8]}... found in {path}"


# ---- unicode ---------------------------------------------------------------------------------------------------------------------------------------

def test_unicode_split_across_chunks_is_delivered_intact(env):
    fake, user = env["fake"], env["user"]
    reply = "Привет, мир! 你好，世界 🌍🚀 — naïve café"
    fake.chunks, fake.chunk_delay = [reply[i:i + 2] for i in range(0, len(reply), 2)], 0.0
    sid = str(uuid.uuid4())
    status, events = run_stream(user, "say hello in many scripts", sid)
    assert events[-1]["type"] == "done"
    assert "".join(e["text"] for e in events if e["type"] == "chunk") == reply
    assert transcript(user, sid)[-1] == ("assistant", reply)


# ---- zero output / identical-key replay -----------------------------------------------------------------------------------------------------------

def test_a_provider_that_answers_with_nothing_terminates_cleanly(env):
    fake, user = env["fake"], env["user"]
    fake.chunks = []
    status, events = run_stream(user, "say nothing", str(uuid.uuid4()))
    assert status == 200 and events[-1]["type"] in ("done", "error"), [e["type"] for e in events]    # never a hung stream


def test_duplicate_delivery_replays_once_without_a_second_dispatch_or_charge(env):
    fake, user = env["fake"], env["user"]
    fake.chunks, fake.chunk_delay = ["dup ", "answer"], 0.05
    sid, key = str(uuid.uuid4()), str(uuid.uuid4())
    used = _usage(user)
    _, first = run_stream(user, "idempotent question", sid, key=key)
    calls = answering_calls(fake, "idempotent question")
    _, second = run_stream(user, "idempotent question", sid, key=key)
    assert first[-1]["type"] == "done" and second[-1].get("idempotent_replay") is True
    assert answering_calls(fake, "idempotent question") == calls == 1
    assert _usage(user) - used == 1
    assert len([r for r in transcript(user, sid) if r[0] == "assistant"]) == 1
