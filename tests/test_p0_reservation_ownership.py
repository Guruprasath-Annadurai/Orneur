"""P0-2: reservation ownership, fingerprint, no consumed/in-progress replay."""

from __future__ import annotations

import uuid

import pytest


def _user(uid: str, tier: str = "free"):
    from orca.auth.store import User

    return User(id=uid, email=f"{uid}@example.com", name=uid, tier=tier, verified=True)


def test_cross_user_request_id_theft_rejected(isolated_home):
    from orca.auth.db import init_db
    from orca.auth.store import QuotaError, reservation_fingerprint, reserve_quota

    init_db()
    fp = reservation_fingerprint(user_id="owner", kind="message", session_id="s1", model="m", message="hi")
    assert reserve_quota("owner", "free", "message", request_id="shared-rid", fingerprint=fp)["ok"]
    with pytest.raises(QuotaError) as exc:
        reserve_quota("thief", "free", "message", request_id="shared-rid", fingerprint=fp)
    assert exc.value.code == "reservation_forbidden"


def test_consumed_reservation_never_readmits_provider_call(isolated_home, ollama_fixture):
    from orca.auth.db import init_db
    from orca.auth.store import get_usage_today, increment_usage
    from orca.serve.inference import InferenceError, complete

    init_db()
    uid = "cap50"
    for _ in range(49):
        increment_usage(uid, "message")
    rid = "replay-me"
    first = complete(
        user=_user(uid),
        message="hello",
        model="fixture-llama",
        host=ollama_fixture,
        session_id="sessAxxxxxxx",
        request_id=rid,
        synthetic_provider=True,
    )
    assert first["request_id"] == rid
    assert get_usage_today(uid)["messages"] == 50

    calls = {"n": 0}

    def _transport(host, model, prompt):
        calls["n"] += 1
        return {"response": "SHOULD_NOT_RUN", "model": model, "prompt_eval_count": 1, "eval_count": 1}

    replayed = complete(
        user=_user(uid),
        message="hello",
        model="fixture-llama",
        host=ollama_fixture,
        session_id="sessAxxxxxxx",
        request_id=rid,
        transport_generate=_transport,
        synthetic_provider=True,
    )
    assert calls["n"] == 0
    assert replayed.get("replayed") is True
    assert replayed["text"] == first["text"]
    assert get_usage_today(uid)["messages"] == 50

    with pytest.raises(InferenceError) as exc:
        complete(
            user=_user(uid),
            message="other",
            model="fixture-llama",
            host=ollama_fixture,
            session_id="sessBxxxxxxx",
            request_id=uuid.uuid4().hex,
            synthetic_provider=True,
        )
    assert exc.value.code == "quota_exceeded"


def test_in_progress_duplicate_rejected_and_fingerprint_mismatch(isolated_home):
    from orca.auth.db import init_db
    from orca.auth.store import QuotaError, reservation_fingerprint, reserve_quota

    init_db()
    fp = reservation_fingerprint(user_id="u1", kind="message", session_id="s", model="m", message="a")
    assert reserve_quota("u1", "free", "message", request_id="inflight", fingerprint=fp)["ok"]
    again = reserve_quota("u1", "free", "message", request_id="inflight", fingerprint=fp)
    assert again["ok"] is False and again["status"] == "in_progress"
    other = reservation_fingerprint(user_id="u1", kind="message", session_id="s", model="m", message="b")
    with pytest.raises(QuotaError) as exc:
        reserve_quota("u1", "free", "message", request_id="inflight", fingerprint=other)
    assert exc.value.code == "reservation_mismatch"


def test_expiry_during_live_inference_refunds_and_retry_after_completion(isolated_home, monkeypatch):
    from orca.auth.db import init_db
    from orca.auth.store import get_usage_today, mark_quota_consumed, release_quota, reserve_quota

    init_db()
    uid = "exp-live"
    monkeypatch.setattr("orca.auth.store.RESERVATION_TTL_S", 0)
    reserve_quota(uid, "free", "message", request_id="stale-live", fingerprint="fp")
    assert get_usage_today(uid)["messages"] == 1
    ok = reserve_quota(uid, "free", "message", request_id="fresh-live", fingerprint="fp2")
    assert ok["ok"] is True
    assert get_usage_today(uid)["messages"] == 1
    mark_quota_consumed("fresh-live", response={"text": "done"})
    again = reserve_quota(uid, "free", "message", request_id="fresh-live", fingerprint="fp2")
    assert again["ok"] is False and again["status"] == "consumed" and again["replay"]["text"] == "done"
    assert get_usage_today(uid)["messages"] == 1
    release_quota("fresh-live")
    assert get_usage_today(uid)["messages"] == 1
