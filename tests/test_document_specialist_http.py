from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orca.auth.db import init_db
from orca.auth.store import create_user
from orca.serve.document_routes import router as document_router
from orca.sovereign_mission.service import SovereignMission
from orca.specialists.routes import router as specialist_router


@pytest.fixture()
def auth_db(tmp_path, monkeypatch):
    monkeypatch.setattr("orca.auth.db.AUTH_DB", tmp_path / "auth.db")
    monkeypatch.setattr("orca.serve.uploads.ORCA_HOME", tmp_path)
    init_db()
    return tmp_path


def _client():
    app = FastAPI()
    app.include_router(document_router)
    app.include_router(specialist_router)
    return TestClient(app)


def _token(email: str) -> str:
    create_user(email, "correct-horse", email.split("@")[0])
    engine = SovereignMission()
    return engine.login(email, "correct-horse")


def test_http_document_task_is_owner_scoped(auth_db):
    owner = _token("owner@example.com")
    other = _token("intruder@example.com")
    client = _client()
    uploaded = client.post(
        "/api/documents/tasks",
        headers={"Authorization": f"Bearer {owner}"},
        files={"upload": ("note.txt", b"The indigo widget torque is 12 newton metres.", "text/plain")},
        data={"question": "indigo widget torque"},
    )
    assert uploaded.status_code == 200
    body = uploaded.json()
    assert body["claims"]["answer_grounding"] == "not_performed"
    assert body["claims"]["citation_excerpt_consistency"] == "verified"
    denied = client.get("/api/documents/note.txt", headers={"Authorization": f"Bearer {other}"})
    assert denied.status_code == 404
    owner_read = client.get("/api/documents/note.txt", headers={"Authorization": f"Bearer {owner}"})
    assert owner_read.status_code == 200
    forged = client.post(
        "/api/documents",
        headers={"Authorization": f"Bearer {other}"},
        files={"upload": ("note.txt", b"intruder", "text/plain")},
        data={"owner_user_id": "ignored"},
    )
    assert forged.status_code == 200
    other_read = client.get("/api/documents/note.txt", headers={"Authorization": f"Bearer {other}"})
    assert other_read.json()["nbytes"] == 8
    owner_still = client.get("/api/documents/note.txt", headers={"Authorization": f"Bearer {owner}"})
    assert owner_still.json()["nbytes"] != 8


def test_http_specialists_cannot_escalate(auth_db):
    token = _token("owner@example.com")
    client = _client()
    denied = client.post(
        "/api/specialists/run",
        headers={"Authorization": f"Bearer {token}"},
        json={"tasks": [{"task_id": "p", "role": "planning", "payload": {"tasks": [{"id": "a"}]}}], "capabilities": ["god.mode"]},
    )
    assert denied.status_code == 403
    ok = client.post(
        "/api/specialists/run",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "tasks": [
                {"task_id": "p", "role": "planning", "payload": {"tasks": [{"id": "a"}, {"id": "b", "depends_on": ["a"]}]}}
            ]
        },
    )
    assert ok.status_code == 200
    assert ok.json()["results"]["p"]["output"]["order"] == ["a", "b"]
    anon = client.post("/api/specialists/run", json={"tasks": []})
    assert anon.status_code == 401
