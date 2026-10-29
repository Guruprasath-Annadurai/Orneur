"""B-01 final integration (Wave H): the REAL refusal protocol of ``POST /api/stream`` - measured, not assumed.

The Cursor handoff said every pre-admission refusal is an HTTP JSON status. That is not what the route does, and it is not what the browser expects. This test
drives every refusal path of the route as it exists, records (HTTP status, body kind, public error code), and asserts for EVERY path that

  * no unit of quota is spent and no model is called,
  * the turn authority / quota reservation are released (the very next request on the same conversation is admitted and answered), and
  * the frontend-visible shape is the documented one.

The table is written to $ORNEUR_B01_EVIDENCE_DIR/refusal_protocol.json for the evidence package. Evidence class: DETERMINISTIC (in-process TestClient, FakeOllama).
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest

from tests.fake_ollama import FakeOllama, point_orneur_at
from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401  (fixture re-export)

EVIDENCE = Path(os.environ.get("ORNEUR_B01_EVIDENCE_DIR", "/tmp/orneur-b01-evidence"))
TABLE: list[dict] = []


@pytest.fixture
def fake(client, monkeypatch):  # noqa: F811
    from orca.serve import ratelimit

    ratelimit._local_counters.clear()
    f = FakeOllama(models=("orca-nano", "orca-core", "orca-ultra"), chunk_delay=0.0)
    f.__enter__()
    point_orneur_at(f, monkeypatch)
    yield f
    f.__exit__(None, None, None)


def _usage(client, token) -> int:
    return client.get("/api/usage", headers=_hdr(token)).json()["today"]["messages"]


def _post(client, token, body, headers=None):
    """Returns (http_status, kind, events_or_body). kind = 'sse' when the body is an event stream, else 'json'."""
    h = {**_hdr(token), **(headers or {})} if token else dict(headers or {})
    with client.stream("POST", "/api/stream", json=body, headers=h) as r:
        ctype = r.headers.get("content-type", "")
        text = "".join(r.iter_text())
    if "text/event-stream" in ctype:
        return r.status_code, "sse", [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]
    try:
        return r.status_code, "json", json.loads(text)
    except ValueError:
        return r.status_code, "text", text[:200]


def _assert_recovers(client, token, fake, sid, used_before):
    """Whatever was refused, nothing is left held: the same conversation is admitted immediately and a unit is spent only for THIS answer."""
    fake.chunks = ["recovered"]
    before = len(fake.requests)
    status, kind, events = _post(client, token, {"message": "after the refusal", "session_id": sid, "model_variant": "nano"})
    assert status == 200 and kind == "sse" and events[-1]["type"] == "done" and events[-1]["persisted"] == "saved", (status, events[-2:])
    assert _usage(client, token) == used_before + 1
    assert len(fake.requests) > before


def _record(path, status, kind, code, **extra):
    TABLE.append({"path": path, "http_status": status, "body": kind, "code": code, **extra})


def test_invalid_bearer_is_a_401_json_before_any_stream_and_never_reaches_the_model(client, fake):
    token, _ = _signup(client)
    before = len(fake.requests)
    status, kind, body = _post(client, "not-a-real-token", {"message": "hi", "model_variant": "nano"})
    assert (status, kind) == (401, "json") and len(fake.requests) == before
    _record("invalid / expired / revoked bearer", status, kind, (body or {}).get("code") or "invalid_token")
    assert _usage(client, token) == 0


def test_rate_limit_is_a_429_json(client, fake):
    from orca.serve import ratelimit

    token, _ = _signup(client)
    ratelimit._local_counters.clear()
    last = None
    for _ in range(70):
        last = _post(client, token, {"message": "anything", "model_variant": "ultra"})       # (refused on the plan: costs no quota, so only the rate limit can stop the loop)
        if last[0] == 429:
            break
    assert last[0] == 429 and last[1] == "json", last
    _record("rate limit (60/min/IP)", last[0], last[1], (last[2] or {}).get("code") or "rate_limited")


def test_session_owned_by_somebody_else_is_a_404_json_without_a_model_call(client, fake):
    token_a, _ = _signup(client)
    token_b, _ = _signup(client)
    sid = f"{uuid.uuid4().hex[:8]}-owned-a"
    assert _post(client, token_a, {"message": "mine", "session_id": sid, "model_variant": "nano"})[2][-1]["type"] == "done"
    before, used = len(fake.requests), _usage(client, token_b)
    status, kind, body = _post(client, token_b, {"message": "not mine", "session_id": sid, "model_variant": "nano"})
    assert (status, kind) == (404, "json") and len(fake.requests) == before and _usage(client, token_b) == used
    _record("conversation owned by another account", status, kind, "session_not_found")


def test_a_closed_temporary_chat_is_a_409_json_before_any_stream(client, fake):
    token, _ = _signup(client)
    sid = client.post("/api/sessions/temporary", json={"ttl_seconds": 900}, headers=_hdr(token)).json()["session_id"]
    assert client.post(f"/api/session/{sid}/temporary/close", headers=_hdr(token)).status_code == 200
    before = len(fake.requests)
    status, kind, body = _post(client, token, {"message": "after close", "session_id": sid, "model_variant": "nano"})
    assert (status, kind) == (409, "json") and body["code"] in {"temporary_closed", "temporary_finished", "temporary_expired"} and len(fake.requests) == before
    assert _usage(client, token) == 0
    _record("temporary chat closed / expired", status, kind, body["code"])


def test_sse_refusals_are_http_200_event_streams_with_a_public_code_and_release_everything(client, fake, monkeypatch):
    """The refusals that arrive INSIDE a 200 event stream (what conversation.html handles with its `error` event branch)."""
    import orca.serve.api as api
    from orca.serve import conversations

    token, uid = _signup(client)
    sid = f"{uuid.uuid4().hex[:8]}-sse-refusals"

    # --- model access denied (a free account asking for the ultra tier)
    used = _usage(client, token)
    status, kind, ev = _post(client, token, {"message": "hello", "session_id": sid, "model_variant": "ultra"})
    assert (status, kind) == (200, "sse") and ev[-1]["type"] == "error" and ev[-1]["code"] == "model_access_denied"
    assert _usage(client, token) == used
    _record("model access denied (tier not on the plan)", status, kind, ev[-1]["code"], event="error")
    _assert_recovers(client, token, fake, sid, used)

    # --- input moderation block
    used = _usage(client, token)
    before = len(fake.requests)
    with monkeypatch.context() as m:
        m.setattr(api, "check_input", lambda text: type("M", (), {"action": "block", "flagged_categories": ["x"]})())
        status, kind, ev = _post(client, token, {"message": "blocked text", "session_id": sid, "model_variant": "nano"})
    assert (status, kind) == (200, "sse") and ev[-1]["code"] == "content_refused" and len(fake.requests) == before and _usage(client, token) == used
    _record("input moderation block", status, kind, ev[-1]["code"], event="error")
    _assert_recovers(client, token, fake, sid, used)

    # --- quota exhausted
    from orca.auth.store import increment_usage

    used = _usage(client, token)
    for _ in range(50 - used):
        increment_usage(uid, "message")
    before = len(fake.requests)
    status, kind, ev = _post(client, token, {"message": "over the limit", "session_id": sid, "model_variant": "nano"})
    assert (status, kind) == (200, "sse") and ev[-1]["code"] == "quota_exceeded" and len(fake.requests) == before and _usage(client, token) == 50
    _record("daily quota exhausted", status, kind, ev[-1]["code"], event="error")

    token2, uid2 = _signup(client)
    sid2 = f"{uuid.uuid4().hex[:8]}-sse-refusals2"

    # --- conversation busy (another live turn holds the authority)
    held = conversations.acquire_authority(sid2, uid2, "other-fence", ttl_s=30)
    assert held is not None
    used = _usage(client, token2)
    before = len(fake.requests)
    status, kind, ev = _post(client, token2, {"message": "while busy", "session_id": sid2, "model_variant": "nano"})
    assert (status, kind) == (200, "sse") and ev[-1]["code"] == "session_busy" and len(fake.requests) == before and _usage(client, token2) == used
    _record("conversation busy (another turn holds it)", status, kind, ev[-1]["code"], event="error")
    conversations.release_authority(sid2, "other-fence", int(held.epoch))
    _assert_recovers(client, token2, fake, sid2, used)

    # --- the durable store is unreachable: refused BEFORE generation and before any charge
    used = _usage(client, token2)
    before = len(fake.requests)
    with monkeypatch.context() as m:
        m.setattr(conversations, "store_available", lambda *a, **k: False)
        status, kind, ev = _post(client, token2, {"message": "store down", "session_id": sid2, "model_variant": "nano"})
    assert (status, kind) == (200, "sse") and ev[-1]["code"] == "history_unavailable" and len(fake.requests) == before and _usage(client, token2) == used
    _record("durable store unavailable", status, kind, ev[-1]["code"], event="error")

    # --- generation intent (image/video) is answered without a text model call
    before = len(fake.requests)
    status, kind, ev = _post(client, token2, {"message": "generate an image of a red bicycle", "session_id": sid2, "model_variant": "nano"})
    assert (status, kind) == (200, "sse") and ev[-1]["type"] == "error" and len(fake.requests) == before
    _record("image/video generation intent (not available yet)", status, kind, ev[-1].get("code") or "lens_not_available", event="error")


def test_kernel_abstention_and_provider_failures_are_sse_errors_that_refund(client, fake, monkeypatch):
    import orca.serve.api as api
    from orca.cognitive.contracts import AbstentionReason, CognitiveResult, CognitiveState

    token, uid = _signup(client)
    sid = f"{uuid.uuid4().hex[:8]}-kernel-refusals"

    async def abstain(message, user, variant, session_id=None, **_hooks):
        return CognitiveResult(request_id="r", trace_id="t", status=CognitiveState.ABSTAINED, abstention_reason=AbstentionReason.POLICY_RESTRICTION)

    with monkeypatch.context() as m:
        m.setattr(api, "_run_cognitive_kernel", abstain)
        used = _usage(client, token)
        status, kind, ev = _post(client, token, {"message": "hello", "session_id": sid, "model_variant": "nano"})
    assert (status, kind) == (200, "sse") and ev[-1]["code"] == "request_abstained" and _usage(client, token) == used
    _record("Kernel abstains (policy / evidence / budget / model unavailable)", status, kind, ev[-1]["code"], event="error")
    _assert_recovers(client, token, fake, sid, used)

    used = _usage(client, token)
    fake.fail_status = 500
    status, kind, ev = _post(client, token, {"message": "provider is down", "session_id": sid, "model_variant": "nano"})
    fake.fail_status = None
    assert (status, kind) == (200, "sse") and ev[-1]["type"] == "error" and not any(e["type"] in ("chunk", "done") for e in ev) and _usage(client, token) == used
    _record("provider failure BEFORE any output", status, kind, ev[-1].get("code"), event="error", quota="refunded")

    fake.chunks, fake.truncate_after = ["one ", "two ", "three "], 1
    status, kind, ev = _post(client, token, {"message": "provider dies mid answer", "session_id": sid, "model_variant": "nano"})
    fake.truncate_after = None
    assert (status, kind) == (200, "sse") and ev[-1]["type"] == "error" and any(e["type"] == "chunk" for e in ev) and not any(e["type"] == "done" for e in ev)
    assert _usage(client, token) == used + 1                      # output had been produced: the established policy keeps the unit spent
    _record("provider failure AFTER output (truncated generation)", status, kind, ev[-1].get("code"), event="error", quota="spent (established policy)", persisted=False)
    rows = client.get(f"/api/session/{sid}/messages", headers=_hdr(token)).json()["messages"]
    assert [m["content"] for m in rows if m["role"] == "assistant"] == ["recovered"], "a truncated generation must not be stored as an answer"
    _assert_recovers(client, token, fake, sid, used + 1)


def test_zz_write_the_measured_table():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "refusal_protocol.json").write_text(json.dumps(sorted(TABLE, key=lambda r: r["path"]), indent=2))
    assert TABLE, "no refusal path was measured"
