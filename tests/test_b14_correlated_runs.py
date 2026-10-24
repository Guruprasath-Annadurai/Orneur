"""B14: one run id correlates streams the same account owns.

The run does not grant the other account access to either conversation.
"""
from __future__ import annotations

import pytest

from tests.fake_ollama import FakeOllama, point_orneur_at
from tests.test_b10_generation_state import _events
from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401


@pytest.fixture
def fake(client, monkeypatch):
    from orca.serve import ratelimit

    ratelimit._local_counters.clear()
    with FakeOllama(reply="The answer is 42.", chunks=("The answer ", "is 42.")) as backend:
        point_orneur_at(backend, monkeypatch)
        yield backend


def test_two_sessions_share_one_run_and_another_account_cannot_see_it(client, fake):
    owner, _owner_id = _signup(client)
    other, _other_id = _signup(client)
    headers = _hdr(owner)
    created = client.post("/api/runs", headers=headers)
    assert created.status_code == 200, created.text
    run_id = created.json()["run_id"]
    assert created.json()["count"] == 0
    first = _events(client, headers, {"message": "hello from one", "model_variant": "nano"}, {"X-Run-Id": run_id})
    second_session = _events(client, headers, {"message": "hello from two", "model_variant": "nano"})
    second_sid = next(event["session_id"] for event in second_session if event["type"] == "session")
    second = _events(
        client, headers,
        {"message": "hello from two again", "session_id": second_sid, "model_variant": "nano"},
        {"X-Run-Id": run_id},
    )
    first_generation = next(event for event in first if event["type"] == "generation")
    second_generation = next(event for event in second if event["type"] == "generation")
    assert first_generation["run_id"] == run_id
    assert second_generation["run_id"] == run_id
    assert first_generation["session_id"] != second_generation["session_id"]
    listed = client.get(f"/api/runs/{run_id}", headers=headers)
    assert listed.status_code == 200
    members = listed.json()["members"]
    assert {item["generation_id"] for item in members} == {
        first_generation["generation_id"],
        second_generation["generation_id"],
    }
    assert {item["session_id"] for item in members} == {
        first_generation["session_id"],
        second_generation["session_id"],
    }
    assert client.get(f"/api/runs/{run_id}", headers=_hdr(other)).status_code == 404
    stolen = client.post(
        "/api/stream",
        json={"message": "not yours", "model_variant": "nano"},
        headers={**_hdr(other), "X-Run-Id": run_id},
    )
    assert stolen.status_code == 404 and stolen.json()["code"] == "run_not_found"
    assert client.get(f"/api/runs/{run_id}", headers=headers).json()["count"] == 2
    plain = _events(client, headers, {"message": "no run header", "model_variant": "nano"})
    assert next(event for event in plain if event["type"] == "generation")["run_id"] is None
