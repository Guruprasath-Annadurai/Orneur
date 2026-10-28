"""First real chatbot journey -- server-side half (evidence class: LIVE_API).

Real ``orca serve`` subprocess + real Ollama, driven over HTTP exactly as the
approved /conversation page drives it. The browser half is in
test_journey_browser.py. A step is "passed" only when BOTH halves pass.

Steps: A login . B new conversation / real response / streaming .
C persistence + reload . D isolation . E edited-message context .
F temporary-chat privacy . G logout + revocation.

Run:  pytest tests/journey -m journey_live -p no:cacheprovider -v
"""
from __future__ import annotations

import time

import pytest

from tests.journey.harness import JOURNEY_MODEL, User, answer_of, session_id_of


@pytest.fixture(scope="module")
def alice(server):
    return User(server.base, "alice")


@pytest.fixture(scope="module")
def bob(server):
    return User(server.base, "bob")


# ---------------------------------------------------------------- A: login

def test_A1_login_issues_a_working_session_token(server, alice):
    """LIVE_API"""
    me = alice.get("/api/auth/me")
    assert me.status_code == 200, me.text
    assert alice.email in me.text


def test_A2_wrong_password_and_missing_token_are_refused(server, alice):
    """LIVE_API"""
    import httpx
    bad = httpx.post(f"{server.base}/api/auth/login", json={"email": alice.email, "password": "nope-nope-nope"})
    assert bad.status_code in (400, 401, 403), bad.text
    assert httpx.get(f"{server.base}/api/auth/me").status_code == 401
    assert httpx.get(f"{server.base}/api/sessions", headers={"Authorization": "Bearer not-a-token"}).status_code == 401


# ------------------------------------------------ B: new conversation + live model + streaming

def test_B1_new_conversation_streams_a_real_ollama_answer(server, alice, tap):
    """LIVE_API -- real model call (verified by the tap), incremental SSE delivery."""
    before = len(tap.requests)
    t0 = time.time()
    arrival = []
    import json, uuid
    with alice.http.stream("POST", "/api/stream", headers={**alice.headers, "Idempotency-Key": str(uuid.uuid4())},
                           json={"message": "Name three colours, comma separated.", "session_id": None, "model_variant": "core"}) as r:
        assert r.status_code == 200, r.read()
        events = []
        for line in r.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
                arrival.append(time.time() - t0)
    kinds = [e["type"] for e in events]
    assert kinds[0] == "session" and "generation" in kinds, kinds
    chunks = [i for i, k in enumerate(kinds) if k == "chunk"]
    assert len(chunks) >= 2, f"not incremental: {kinds}"
    assert kinds[-1] == "done", f"stream did not end with a real done event: {kinds[-3:]}\n{server.log_tail(15)}"
    assert arrival[chunks[-1]] > arrival[chunks[0]], "all chunks arrived at once: not streamed"
    assert answer_of(events).strip()
    assert len(tap.requests) > before, "no request reached Ollama: this was not a real model answer"
    ident = next(e for e in events if e["type"] == "model")["identity"]
    assert ident["backend"] == "ollama" and ident["data_left_infrastructure"] is False


def test_blocker_colon_tags_stream(tmp_path, tap):
    """LIVE_API -- documents a KNOWN BLOCKER; fails until the gateway accepts real Ollama tags.

    Every stock Ollama tag contains ':' (e.g. llama3.2:1b). The gateway derives
    ``deployment_id = "ollama-<model>"`` and orca.registry._ids.validate_id rejects ':',
    so /api/stream dies after the 'model' event without a 'chunk' or 'done'."""
    from tests.journey.harness import live_server
    with live_server(tmp_path, extra_env={"ORNEUR_CORE_MODEL": "llama3.2:1b", "ORNEUR_NANO_MODEL": "llama3.2:1b",
                                         "ORNEUR_ULTRA_MODEL": "llama3.2:1b"}) as srv:
        u = User(srv.base, "colon")
        status, events = u.stream("Say hi.")
        kinds = [e.get("type") for e in events]
        assert status == 200 and "chunk" in kinds and kinds[-1] == "done", (kinds, srv.log_tail(6))


# ------------------------------------------------ C: persistence + reload

def test_C1_transcript_is_persisted_and_listed(server, alice):
    """LIVE_API"""
    status, events = alice.stream("Remember the word kumquat.")
    assert status == 200
    sid = session_id_of(events)
    msgs = alice.get(f"/api/session/{sid}/messages").json()
    assert [m["role"] for m in msgs["messages"]] == ["user", "assistant"], msgs
    assert msgs["messages"][0]["content"] == "Remember the word kumquat."
    assert msgs["messages"][1]["content"].strip() == answer_of(events).strip()
    listed = alice.get("/api/sessions").json()
    assert sid in str(listed)
    alice.__dict__["sid_c"] = sid


def test_C2_conversation_survives_a_full_server_restart(tmp_path, tap):
    """LIVE_API -- new process, same ORNEUR_HOME: a user logs in again and reloads the conversation."""
    from tests.journey.harness import live_server
    env = {"ORNEUR_OLLAMA_HOST": tap.url, "OLLAMA_HOST": tap.url}
    with live_server(tmp_path, extra_env=env) as s1:
        u = User(s1.base, "restart")
        status, events = u.stream("Persist me across restarts.")
        assert status == 200
        sid = session_id_of(events)
        email = u.email
    with live_server(tmp_path, extra_env=env) as s2:
        import httpx
        r = httpx.post(f"{s2.base}/api/auth/login", json={"email": email, "password": "Journey-Pass-91x"})
        assert r.status_code == 200, r.text
        h = {"Authorization": f"Bearer {r.json()['token']}"}
        got = httpx.get(f"{s2.base}/api/session/{sid}/messages", headers=h)
        assert got.status_code == 200, got.text
        assert got.json()["messages"][0]["content"] == "Persist me across restarts."
        assert sid in httpx.get(f"{s2.base}/api/sessions", headers=h).text


# ------------------------------------------------ D: isolation

def test_D1_another_user_cannot_read_stream_into_or_edit_a_conversation(server, alice, bob):
    """LIVE_API"""
    status, events = alice.stream("Alice private note: zebra-7731.")
    sid = session_id_of(events)
    mid = alice.get(f"/api/session/{sid}/messages").json()["messages"][0]["message_id"]
    r = bob.get(f"/api/session/{sid}/messages")
    assert r.status_code in (403, 404) and "zebra-7731" not in r.text, r.text
    assert "zebra-7731" not in bob.get("/api/sessions").text
    assert "zebra-7731" not in bob.get("/api/sessions/search", params={"q": "zebra"}).text
    status, ev = bob.stream("What did Alice write?", session_id=sid)
    assert status in (403, 404) or "zebra-7731" not in answer_of(ev), (status, ev[:3])
    assert status != 200 or sid not in [e.get("session_id") for e in ev if e.get("type") == "session"], \
        "Bob was attached to Alice's session id"
    e = bob.post(f"/api/session/{sid}/messages/{mid}/edits", json={"content": "hijacked"})
    assert e.status_code in (403, 404), e.text
    assert alice.get(f"/api/session/{sid}/messages").json()["messages"][0]["content"].startswith("Alice private")


# ------------------------------------------------ E: edited-message context

def test_E1_edit_changes_the_context_the_model_is_actually_sent(server, alice, tap):
    """LIVE_API -- asserts on the recorded Ollama request, not on what a 1B model says."""
    status, events = alice.stream("My favourite fruit is pineapple.")
    sid = session_id_of(events)
    mid = alice.get(f"/api/session/{sid}/messages").json()["messages"][0]["message_id"]
    edit = alice.post(f"/api/session/{sid}/messages/{mid}/edits", json={"content": "My favourite fruit is mango."})
    assert edit.status_code == 200 and edit.json()["created"] is True, edit.text
    assert edit.json()["live_sync"] is True, "edit claimed no live sync"
    n = len(tap.requests)
    status, ev = alice.stream("Which fruit did I say is my favourite? Answer with one word.", session_id=sid)
    assert status == 200 and ev[-1]["type"] == "done", ev[-2:]
    prompt = "Which fruit did I say is my favourite? Answer with one word."
    calls = tap.answer_contexts(prompt, n)
    assert calls, "the answering call never reached Ollama"
    sent = calls[-1]
    assert "favourite fruit is mango" in sent, f"model was not sent the edited message:\n{sent[:800]}"
    assert "pineapple" not in sent, f"model was sent the PRE-EDIT message:\n{sent[:800]}"


def test_E2_model_answers_from_the_edited_context(server, alice):
    """LIVE_API -- model-serving evidence only (a 1B model's answer is not a quality claim)."""
    status, events = alice.stream("My pet is a hamster named Biscuit.")
    sid = session_id_of(events)
    mid = alice.get(f"/api/session/{sid}/messages").json()["messages"][0]["message_id"]
    assert alice.post(f"/api/session/{sid}/messages/{mid}/edits", json={"content": "My pet is a parrot named Biscuit."}).status_code == 200
    _, ev = alice.stream("What kind of animal is my pet? One word.", session_id=sid)
    text = answer_of(ev).lower()
    assert "parrot" in text and "hamster" not in text, text


# ------------------------------------------------ F: temporary-chat privacy

def test_F1_temporary_chat_is_hidden_unshareable_and_deleted_on_close(server, alice, bob):
    """LIVE_API"""
    opened = alice.post("/api/sessions/temporary", json={"ttl_seconds": 3600})
    assert opened.status_code == 200, opened.text
    sid = opened.json()["session_id"]
    status, ev = alice.stream("Temp secret: quokka-5521.", session_id=sid)
    assert status == 200 and ev[-1]["type"] == "done", (ev[-2:], server.log_tail(8))
    assert sid not in alice.get("/api/sessions").text, "temporary chat listed in history"
    assert "quokka-5521" not in alice.get("/api/sessions/search", params={"q": "quokka"}).text
    share = alice.post(f"/api/session/{sid}/shares", json={"grantee": bob.email, "role": "viewer"})
    assert share.status_code >= 400, f"temporary chat was shareable: {share.text}"
    closed = alice.post(f"/api/session/{sid}/temporary/close")
    assert closed.status_code == 200, closed.text
    gone = alice.get(f"/api/session/{sid}/messages")
    assert "quokka-5521" not in gone.text, "transcript survived close"
    status, ev = alice.stream("Are you still there?", session_id=sid)
    assert status == 409, (status, ev[:2])
    assert "quokka-5521" not in alice.get(f"/api/session/{sid}/export").text


# ------------------------------------------------ G: logout + revocation

def test_G1_logout_revokes_the_token_everywhere(server):
    """LIVE_API -- a revoked token must never fall back to anonymous access."""
    import httpx
    u = User(server.base, "leaver")
    status, ev = u.stream("Before logout.")
    sid = session_id_of(ev)
    other_device = httpx.post(f"{server.base}/api/auth/login", json={"email": u.email, "password": "Journey-Pass-91x"}).json()["token"]
    old = u.token
    out = u.post("/api/auth/logout")
    assert out.status_code in (200, 204), out.text
    h = {"Authorization": f"Bearer {old}"}
    assert httpx.get(f"{server.base}/api/auth/me", headers=h).status_code == 401
    assert httpx.get(f"{server.base}/api/sessions", headers=h).status_code == 401
    assert httpx.get(f"{server.base}/api/session/{sid}/messages", headers=h).status_code in (401, 403, 404)
    status, ev = u.stream("After logout.", session_id=sid, token=old)
    assert status == 401, f"revoked token reached /api/stream: status={status} events={ev[:2]}"
    assert httpx.get(f"{server.base}/api/auth/me", headers={"Authorization": f"Bearer {other_device}"}).status_code == 200, \
        "logout must only end this session"


def test_G2_logout_all_revokes_every_device(server):
    """LIVE_API"""
    import httpx
    u = User(server.base, "leaver-all")
    second = httpx.post(f"{server.base}/api/auth/login", json={"email": u.email, "password": "Journey-Pass-91x"}).json()["token"]
    assert u.post("/api/auth/logout-all").status_code in (200, 204)
    for t in (u.token, second):
        assert httpx.get(f"{server.base}/api/auth/me", headers={"Authorization": f"Bearer {t}"}).status_code == 401


# ------------------------------------------------ B3: multi-turn context (isolates blocker J-1 from the edit question)

@pytest.mark.parametrize("follow_up", [
    "What is my lucky number?",
    "Which number did I say is my lucky number? Answer with one word.",
    "Remind me, what number did I tell you?",
])
def test_B3_second_turn_is_sent_the_first_turn(server, alice, tap, follow_up):
    """LIVE_API -- the recorded Ollama request for turn 2 must contain turn 1. Without this,
    'edited-message context' is meaningless: no prior message ever reaches the model.
    Several phrasings because the cognitive kernel routes short questions differently
    (blocker J-1: the kernel-direct route builds a single-turn request)."""
    status, events = alice.stream("My lucky number is 4812.")
    sid = session_id_of(events)
    n = len(tap.requests)
    status, ev = alice.stream(follow_up, session_id=sid)
    assert status == 200 and ev[-1]["type"] == "done"
    route = next(e for e in ev if e["type"] == "model")["identity"].get("substitution_reason")
    calls = tap.answer_contexts(follow_up, n)
    assert calls, "the answering call never reached Ollama"
    sent = calls[-1]
    assert "4812" in sent, f"turn 2 was sent WITHOUT turn 1 (route={route}):\n{sent[:400]}"


def test_B4_chat_endpoint_also_carries_conversation_context(server, alice, tap):
    """LIVE_API -- same check on the canonical /api/chat endpoint."""
    r1 = alice.post("/api/chat", json={"message": "My lucky colour is teal-9921.", "model_variant": "core"})
    assert r1.status_code == 200, r1.text
    sid = r1.json()["session_id"]
    n = len(tap.requests)
    r2 = alice.post("/api/chat", json={"message": "What is my lucky colour?", "session_id": sid, "model_variant": "core"})
    assert r2.status_code == 200, r2.text
    calls = tap.answer_contexts("What is my lucky colour?", n)
    assert calls, "the answering call never reached Ollama"
    sent = calls[-1]
    assert "teal-9921" in sent, f"/api/chat turn 2 was sent WITHOUT turn 1:\n{sent[:500]}"


# ------------------------------------------------ E3: two real servers + real Redis (qualified e8e6ab1 behaviour end to end)

@pytest.fixture(scope="module")
def two_servers(tmp_path_factory, tap):
    import redis
    from tests.journey.harness import LiveServer, require_ollama
    url = "redis://localhost:6379/13"
    try:
        redis.from_url(url, socket_connect_timeout=2).flushdb()
    except Exception as exc:
        from tests.journey.harness import CapabilityMissing
        raise CapabilityMissing(f"capability missing: Redis at {url} ({exc!r})")
    require_ollama()
    home = tmp_path_factory.mktemp("two-servers")
    env = {"ORNEUR_OLLAMA_HOST": tap.url, "OLLAMA_HOST": tap.url}
    a = LiveServer(home, redis_url=url, extra_env=env)
    a.wait_ready()
    b = LiveServer(home, redis_url=url, extra_env=env)
    b.wait_ready()
    yield a, b
    a.stop(); b.stop()


def test_E3_edit_on_server_B_is_seen_by_server_A_with_real_redis(two_servers, tap):
    """LIVE_API -- two independent server processes sharing one home + real Redis. The edit is committed
    through B; the next turn goes to A. Asserts the qualified freshness contract AND the context sent."""
    a, b = two_servers
    ua = User(a.base, "e3")
    import httpx
    tok_b = httpx.post(f"{b.base}/api/auth/login", json={"email": ua.email, "password": "Journey-Pass-91x"}).json()["token"]
    hb = {"Authorization": f"Bearer {tok_b}"}
    r1 = ua.post("/api/chat", json={"message": "My favourite fruit is pineapple.", "model_variant": "core"})
    assert r1.status_code == 200, r1.text
    sid = r1.json()["session_id"]
    mid = ua.get(f"/api/session/{sid}/messages").json()["messages"][0]["message_id"]
    edit = httpx.post(f"{b.base}/api/session/{sid}/messages/{mid}/edits", json={"content": "My favourite fruit is mango."}, headers=hb, timeout=60)
    assert edit.status_code == 200 and edit.json()["live_sync"] is True, edit.text
    n = len(tap.requests)
    r2 = ua.post("/api/chat", json={"message": "Which fruit is my favourite? One word.", "session_id": sid, "model_variant": "core"})
    assert r2.status_code == 200, r2.text
    assert r2.json().get("context_freshness") == "confirmed", r2.json().get("context_freshness")
    calls = tap.answer_contexts("Which fruit is my favourite? One word.", n)
    assert calls, "the answering call never reached Ollama"
    sent = calls[-1]
    assert "favourite fruit is mango" in sent and "pineapple" not in sent, f"server A sent the model:\n{sent[:500]}"
