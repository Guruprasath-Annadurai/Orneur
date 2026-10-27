"""B10/B12: a stream has a server-side generation id and a terminal state.

Retry eligibility is a permission to send a new request. It does not
resume the old one and it does not call the model.
"""
from __future__ import annotations

import asyncio
import json
import time

from orca.auth.crypto import create_token
from orca.serve import generations
from tests.fake_ollama import FakeOllama, point_orneur_at
from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401


def _events(client, headers, body, extra_headers=None):
    headers = dict(headers or {})
    if extra_headers:
        headers.update(extra_headers)
    response = client.post("/api/stream", json=body, headers=headers)
    assert response.status_code == 200, response.text
    if response.headers.get("content-type", "").startswith("application/json"):
        return response.json()
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_a_completed_stream_is_readable_and_not_retryable(client, monkeypatch):
    from orca.serve import ratelimit

    ratelimit._local_counters.clear()
    with FakeOllama() as fake:
        point_orneur_at(fake, monkeypatch)
        token, _user = _signup(client)
        headers = _hdr(token)
        events = _events(client, headers, {"message": "hello there", "model_variant": "nano"})
    assert isinstance(events, list)
    generation = next(event for event in events if event["type"] == "generation")
    done = next(event for event in reversed(events) if event["type"] == "done")
    assert done["generation_id"] == generation["generation_id"]
    status = client.get(f"/api/generations/{generation['generation_id']}", headers=headers)
    assert status.status_code == 200
    body = status.json()
    assert body["state"] == "completed"
    assert body["retry_eligible"] is False
    assert body["terminal"] is True
    cancel = client.post(f"/api/generations/{generation['generation_id']}/cancel", headers=headers)
    assert cancel.status_code == 200
    assert cancel.json()["cancel_accepted"] is False
    assert cancel.json()["state"] == "completed"


def test_another_account_cannot_read_or_cancel_a_generation(client, monkeypatch):
    from orca.serve import ratelimit

    ratelimit._local_counters.clear()
    with FakeOllama() as fake:
        point_orneur_at(fake, monkeypatch)
        owner_token, _owner = _signup(client)
        other_token, _other = _signup(client)
        events = _events(client, _hdr(owner_token), {"message": "hello there", "model_variant": "nano"})
    generation_id = next(event["generation_id"] for event in events if event["type"] == "generation")
    assert client.get(f"/api/generations/{generation_id}", headers=_hdr(other_token)).status_code == 404
    assert client.post(f"/api/generations/{generation_id}/cancel", headers=_hdr(other_token)).status_code == 404
    assert client.get(f"/api/generations/{generation_id}", headers=_hdr(owner_token)).json()["state"] == "completed"


def test_expired_token_is_401_on_generation_status(client, monkeypatch):
    from orca.serve import ratelimit

    ratelimit._local_counters.clear()
    with FakeOllama() as fake:
        point_orneur_at(fake, monkeypatch)
        token, user_id = _signup(client)
        events = _events(client, _hdr(token), {"message": "hello there", "model_variant": "nano"})
    generation_id = next(event["generation_id"] for event in events if event["type"] == "generation")
    expired = create_token({"sub": user_id, "type": "session"}, expires_in=-10)
    denied = client.get(f"/api/generations/{generation_id}", headers=_hdr(expired))
    assert denied.status_code == 401


def test_repeated_idempotency_key_does_not_stream_again(client, monkeypatch):
    from orca.serve import ratelimit

    ratelimit._local_counters.clear()
    with FakeOllama() as fake:
        point_orneur_at(fake, monkeypatch)
        token, _user = _signup(client)
        headers = _hdr(token)
        body = {"message": "hello there", "model_variant": "nano"}
        key = {"Idempotency-Key": "stream-key-01"}
        first = _events(client, headers, body, key)
        session_id = next(event["session_id"] for event in first if event["type"] == "session")
        streamed = sum(1 for request in fake.requests if request.get("stream"))
        second = client.post(
            "/api/stream",
            json={**body, "session_id": session_id},
            headers={**headers, **key},
        )
        assert second.status_code == 200
        payload = second.json()
        assert payload["code"] == "generation_already_completed"
        assert payload["generation_id"] == next(event["generation_id"] for event in first if event["type"] == "generation")
        assert sum(1 for request in fake.requests if request.get("stream")) == streamed


def test_cancel_during_stream_stops_the_generation(client, monkeypatch):
    import orca.serve.api as api
    from orca.serve import ratelimit

    ratelimit._local_counters.clear()

    async def drive(token: str):
        path = "/api/stream"
        body = {"message": "hello there", "model_variant": "nano"}
        scope = {
            "type": "http", "method": "POST", "path": path, "raw_path": path.encode(),
            "query_string": b"", "root_path": "", "scheme": "http", "http_version": "1.1",
            "server": ("test", 80), "client": ("9.9.9.9", 1234),
            "headers": [
                (b"content-type", b"application/json"),
                (b"authorization", f"Bearer {token}".encode()),
                (b"host", b"test"),
            ],
        }
        sent = False
        seen: dict[str, str] = {}

        async def receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": json.dumps(body).encode(), "more_body": False}
            await asyncio.sleep(30)
            return {"type": "http.disconnect"}

        async def send(msg):
            raw = msg.get("body") or b""
            if b'"type": "generation"' in raw or b'"type":"generation"' in raw:
                for line in raw.decode().splitlines():
                    if line.startswith("data:"):
                        event = json.loads(line[5:].strip())
                        if event.get("type") == "generation" and event.get("state") == "running":
                            generations.request_cancel(event["generation_id"])
                            seen["id"] = event["generation_id"]

        await api.app(scope, receive, send)
        return seen["id"]

    with FakeOllama(chunks=tuple(f"w{i} " for i in range(20)), chunk_delay=0.05) as fake:
        point_orneur_at(fake, monkeypatch)
        token, _user = _signup(client)
        generation_id = asyncio.run(drive(token))
        assert fake.chunks_sent < 20
    status = client.get(f"/api/generations/{generation_id}", headers=_hdr(token))
    assert status.status_code == 200
    assert status.json()["state"] == "cancelled"
    assert status.json()["retry_eligible"] is True
    assert status.json()["reason"] == "cancel_requested"


def test_stale_running_generation_is_interrupted_unknown():
    now = time.time()
    record = {
        "generation_id": "a" * 32,
        "session_id": "sess",
        "state": "running",
        "cancel_requested": False,
        "delivery": "upstream",
        "cancellable": True,
        "updated_at": now - 60,
        "reason": None,
    }
    view = generations.public(record, now=now)
    assert view["state"] == "interrupted_unknown"
    assert view["retry_eligible"] is True
    assert view["terminal"] is True


def test_finish_does_not_overwrite_a_terminal_state(client):
    record, created = generations.begin(
        session_id="sess-local",
        user_id=None,
        delivery="upstream",
        cancellable=True,
    )
    assert created
    generations.finish(record["generation_id"], "cancelled", reason="cancel_requested")
    again = generations.finish(record["generation_id"], "completed")
    assert again["state"] == "cancelled"
