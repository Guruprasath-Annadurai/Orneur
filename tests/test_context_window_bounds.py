"""LANDMARK-01 Wave 3: the model context is bounded, ends with the current message exactly once, and keeps the MOST RECENT turns."""
from __future__ import annotations

import uuid

import pytest

from tests.fake_ollama import FakeOllama, point_orneur_at
from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401  (fixture re-export)


@pytest.fixture
def fake(client, monkeypatch):  # noqa: F811
    from orca.serve import ratelimit

    monkeypatch.setattr(ratelimit, "enforce", lambda *a, **k: None)
    f = FakeOllama(models=("orca-nano", "orca-core", "orca-ultra"), reply="ok")
    f.__enter__()
    point_orneur_at(f, monkeypatch)
    yield f
    f.__exit__(None, None, None)


def _answering(fake, prompt):
    for req in reversed(fake.requests):
        msgs = req.get("messages") or []
        if msgs and msgs[-1].get("content") == prompt:
            return msgs
    return None


def test_window_never_exceeds_the_limit_and_keeps_recent_turns(client, fake):
    from orca.serve.conversation_context import MAX_MESSAGES

    token, uid = _signup(client)
    sid = f"{uuid.uuid4().hex[:8]}-window"
    from orca.auth.store import DAILY_LIMITS
    assert DAILY_LIMITS["free"]["messages"] >= 40
    for i in range(30):
        r = client.post("/api/chat", json={"message": f"turn-{i:02d}", "session_id": sid, "model_variant": "nano"}, headers=_hdr(token))
        assert r.status_code == 200 and r.json()["persisted"] == "saved", (i, r.text)
        sent = _answering(fake, f"turn-{i:02d}")
        assert sent is not None and len(sent) <= MAX_MESSAGES, (i, len(sent or []))
        assert sent[-1] == {"role": "user", "content": f"turn-{i:02d}"}
        assert sum(1 for m in sent if m["content"] == f"turn-{i:02d}") == 1, "the current message must appear exactly once"
        roles = [m["role"] for m in sent]
        assert all(a != b for a, b in zip(roles, roles[1:])), f"roles must alternate: {roles}"
    final = _answering(fake, "turn-29")
    assert len(final) == MAX_MESSAGES
    assert final[0]["content"] == "turn-06" or final[0]["role"] == "assistant", final[0]
    assert "turn-00" not in "\n".join(m["content"] for m in final) and "turn-28" in "\n".join(m["content"] for m in final)


def test_character_budget_drops_oldest_first_and_keeps_current(client, fake):
    from orca.serve.conversation_context import MAX_CHARS

    token, _ = _signup(client)
    sid = f"{uuid.uuid4().hex[:8]}-chars"
    big = "x" * 9000
    for i in range(5):
        assert client.post("/api/chat", json={"message": f"{i}-{big}", "session_id": sid, "model_variant": "nano"}, headers=_hdr(token)).status_code == 200
    sent = _answering(fake, f"4-{big}")
    assert sum(len(m["content"]) for m in sent) <= MAX_CHARS
    assert sent[-1]["content"] == f"4-{big}"
    assert not any(m["content"].startswith("0-") for m in sent), "the oldest turn should have been dropped first"


def test_another_users_session_never_contributes_context(client, fake):
    alice, _ = _signup(client)
    bob, _ = _signup(client)
    sid = f"{uuid.uuid4().hex[:8]}-private"
    assert client.post("/api/chat", json={"message": "alice-secret-zebra-7731", "session_id": sid, "model_variant": "nano"}, headers=_hdr(alice)).status_code == 200
    n = len(fake.requests)
    r = client.post("/api/chat", json={"message": "what did alice say?", "session_id": sid, "model_variant": "nano"}, headers=_hdr(bob))
    assert r.status_code == 404
    assert "zebra-7731" not in str(fake.requests[n:]), "another account's history reached the model"
