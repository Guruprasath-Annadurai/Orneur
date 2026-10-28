"""FOUNDATION LANDMARK-01 — atomic quota admission on chatbot routes."""
from __future__ import annotations

import threading
import uuid

import pytest

from orca.auth.db import init_db
from orca.auth.store import (
    DAILY_LIMITS,
    create_user,
    get_usage_today,
    mark_quota_consumed,
    reservation_fingerprint,
    reserve_quota,
)
from orca.serve.admission import admit_serving, consume_admission, release_admission


@pytest.fixture()
def user(isolated_home, monkeypatch):
    init_db()
    monkeypatch.setitem(DAILY_LIMITS["free"], "messages", 50)
    return create_user(f"q-{uuid.uuid4().hex[:8]}@example.com", "password-q-12", "Q")


def test_concurrent_admit_at_49_of_50(user, monkeypatch):
    """Exactly one of three concurrent admits succeeds when 49/50 used."""
    # Seed 49 consumed messages.
    for i in range(49):
        rid = f"seed-{i}"
        fp = reservation_fingerprint(user_id=user.id, kind="message", session_id="s", model="nano", message=str(i))
        r = reserve_quota(user.id, user.tier, "message", request_id=rid, fingerprint=fp)
        assert r["ok"], r
        mark_quota_consumed(rid, response={"i": i})
    assert get_usage_today(user.id).get("messages", 0) == 49

    results: list[dict] = []
    lock = threading.Lock()

    def _one(n: int) -> None:
        admission = admit_serving(
            user=user,
            message=f"msg-{n}",
            model="nano",
            session_id=f"sess-{n}",
            route="/api/chat",
            request_id=f"race-{n}-{uuid.uuid4().hex[:8]}",
            allow_anonymous=False,
        )
        with lock:
            results.append(
                {
                    "ok": admission.ok,
                    "refusal": getattr(admission.refusal, "code", None) if admission.refusal else None,
                    "status": admission.reservation.get("status"),
                }
            )
        if admission.ok:
            consume_admission(admission, response={"n": n})

    threads = [threading.Thread(target=_one, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    admitted = sum(1 for r in results if r["ok"])
    assert admitted == 1, results
    assert get_usage_today(user.id).get("messages", 0) == 50


def test_cross_user_request_id_theft_refused(user, isolated_home):
    other = create_user(f"o-{uuid.uuid4().hex[:8]}@example.com", "password-o-12", "O")
    rid = "shared-request-id"
    fp = reservation_fingerprint(user_id=user.id, kind="message", session_id="s", model="nano", message="hi")
    first = reserve_quota(user.id, user.tier, "message", request_id=rid, fingerprint=fp)
    assert first["ok"]
    mark_quota_consumed(rid, response={"text": "owner-response"})

    stolen = admit_serving(
        user=other,
        message="hi",
        model="nano",
        session_id="s",
        route="/api/chat",
        request_id=rid,
        allow_anonymous=False,
    )
    assert stolen.ok is False
    assert stolen.replay is None
    assert stolen.refusal is not None


def test_consumed_replay_does_not_redispatch(user):
    rid = "replay-me"
    fp = reservation_fingerprint(user_id=user.id, kind="message", session_id="s1", model="nano", message="same")
    first = reserve_quota(user.id, user.tier, "message", request_id=rid, fingerprint=fp)
    assert first["ok"]
    mark_quota_consumed(rid, response={"text": "cached-answer", "request_id": rid})

    again = admit_serving(
        user=user,
        message="same",
        model="nano",
        session_id="s1",
        route="/api/chat",
        request_id=rid,
        allow_anonymous=False,
    )
    assert again.ok is False
    assert again.replay is not None
    assert again.replay.get("text") == "cached-answer"
    # Usage must stay at 1 (no second charge).
    assert get_usage_today(user.id).get("messages", 0) == 1


def test_release_after_failure_refunds(user):
    admission = admit_serving(
        user=user,
        message="will-fail",
        model="nano",
        session_id="s-fail",
        route="/api/chat",
        request_id="fail-1",
        allow_anonymous=False,
    )
    assert admission.ok
    assert get_usage_today(user.id).get("messages", 0) == 1
    release_admission(admission)
    assert get_usage_today(user.id).get("messages", 0) == 0
