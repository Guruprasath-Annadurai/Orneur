from __future__ import annotations

import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orca.auth.db import init_db
from orca.auth.store import create_user
from orca.serve.inference import reset_for_tests, set_history_path
from orca.serve.inference_routes import router
from orca.sovereign_mission.service import SovereignMission


@pytest.fixture()
def auth_db(tmp_path, monkeypatch):
    monkeypatch.setattr("orca.auth.db.AUTH_DB", tmp_path / "auth.db")
    init_db()
    set_history_path(tmp_path / "turns.sqlite")
    reset_for_tests()
    yield tmp_path
    set_history_path(None)


def test_http_inference_requires_auth_and_blocks_without_ollama(auth_db, monkeypatch):
    monkeypatch.setattr("orca.serve.inference_routes.CONFIG.ollama.host", "http://127.0.0.1:1")
    create_user("owner@example.com", "correct-horse", "owner")
    token = SovereignMission().login("owner@example.com", "correct-horse")
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    anon = client.post("/api/inference/complete", json={"message": "hi", "model": "fixture-llama"})
    assert anon.status_code == 401
    blocked = client.post(
        "/api/inference/complete",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "hi", "model": "fixture-llama"},
    )
    assert blocked.status_code == 503
    assert blocked.json()["detail"]["code"] == "provider_unavailable"


def test_http_authenticated_live_complete_stream_history_or_block(auth_db, monkeypatch):
    try:
        tags = httpx.get("http://127.0.0.1:11434/api/tags", timeout=1.0)
        tags.raise_for_status()
        names = [row.get("name") for row in tags.json().get("models") or [] if row.get("name")]
    except Exception:
        names = []
    if not names:
        pytest.skip("BLOCKED: live Ollama model is not installed for HTTP integration")
    monkeypatch.setattr("orca.serve.inference_routes.CONFIG.ollama.host", "http://127.0.0.1:11434")
    create_user("owner@example.com", "correct-horse", "owner")
    create_user("other@example.com", "correct-horse", "other")
    owner = SovereignMission().login("owner@example.com", "correct-horse")
    other = SovereignMission().login("other@example.com", "correct-horse")
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    model = names[0]
    first = client.post(
        "/api/inference/complete",
        headers={"Authorization": f"Bearer {owner}"},
        json={"message": "Remember the codeword MAGENTA-42.", "model": model},
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["live"] is True
    assert body["backend"] == "ollama"
    assert body["native_family"] is None
    assert body["text"]
    hist = client.get("/api/inference/history", headers={"Authorization": f"Bearer {owner}"})
    assert hist.status_code == 200
    messages = hist.json()["messages"]
    assert any("MAGENTA-42" in row["content"] for row in messages)
    other_hist = client.get("/api/inference/history", headers={"Authorization": f"Bearer {other}"})
    assert other_hist.status_code == 200
    assert other_hist.json()["messages"] == []
    with client.stream(
        "POST",
        "/api/inference/stream",
        headers={"Authorization": f"Bearer {owner}"},
        json={"message": "Say one short sentence.", "model": model},
    ) as streamed:
        assert streamed.status_code == 200
        events = []
        for line in streamed.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    kinds = [item.get("type") for item in events]
    assert "chunk" in kinds or "done" in kinds or "error" in kinds
    if events and events[-1].get("type") == "error":
        pytest.fail(f"live stream error: {events[-1]}")
    assert "error" not in kinds
    native = client.post(
        "/api/inference/complete",
        headers={"Authorization": f"Bearer {owner}"},
        json={"message": "hi", "model": "genesis"},
    )
    assert native.status_code == 409
    assert native.json()["detail"]["code"] == "native_identity_refused"
