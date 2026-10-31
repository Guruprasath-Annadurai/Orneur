from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orca.auth.db import init_db
from orca.auth.store import create_user
from orca.sovereign_mission import states
from orca.sovereign_mission.service import MissionError, SovereignMission
from orca.sovereign_mission.routes import router

_NOW = datetime(2026, 10, 26, tzinfo=timezone.utc)


@pytest.fixture()
def auth_db(tmp_path, monkeypatch):
    monkeypatch.setattr("orca.auth.db.AUTH_DB", tmp_path / "auth.db")
    init_db()
    import orca.sovereign_mission.routes as routes
    import orca.sovereign_mission.service as mission_service
    import orca.sovereign_mission.store as mission_store

    routes._missions = None
    mission_service._LIVE.clear()
    mission_service._STOP.clear()
    mission_service._PUMPS.clear()
    mission_store._READY.clear()
    return tmp_path


def _user(email: str, password: str = "correct-horse"):
    create_user(email, password, email.split("@")[0])
    engine = SovereignMission()
    token = engine.login(email, password)
    return engine.session_user(token), token, engine


def _authorized_marker(engine, user, text="held"):
    mission = engine.create(user, "pause before effect")
    planned = engine.save_plan(
        user,
        mission["id"],
        [{"tool": "local_marker", "arguments": {"name": "marker.txt", "text": text}}],
    )
    engine.request_approval(user, mission["id"])
    step_id = planned["steps"][0]["id"]
    engine.approve(user, mission["id"], step_id, ttl_seconds=60, now=_NOW)
    return mission["id"], step_id


def test_pause_resume_before_effect(auth_db):
    user, _token, engine = _user("owner@example.com")
    mission_id, step_id = _authorized_marker(engine, user)
    paused = engine.pause(user, mission_id)
    assert paused["state"] == states.PAUSED
    with pytest.raises(MissionError) as exc:
        engine.dispatch(user, mission_id, step_id, now=_NOW)
    assert exc.value.code == "not_authorized"
    marker = auth_db / "marker.txt"
    assert not marker.exists()
    resumed = engine.resume(user, mission_id)
    assert resumed["state"] == states.AUTHORIZED
    engine.dispatch(user, mission_id, step_id, now=_NOW)
    marker = auth_db / "sovereign" / user.id / mission_id / "marker.txt"
    assert marker.read_text(encoding="utf-8") == "held"


def test_pause_refused_after_effect_and_other_user(auth_db):
    owner, _, engine = _user("owner@example.com")
    other, _, other_engine = _user("intruder@example.com")
    mission_id, step_id = _authorized_marker(engine, owner, text="once")
    engine.dispatch(owner, mission_id, step_id, now=_NOW)
    with pytest.raises(MissionError) as exc:
        engine.pause(owner, mission_id)
    assert exc.value.code in {"pause_unsafe", "pause_refused"}
    with pytest.raises(MissionError) as exc:
        engine.pause(other, mission_id)
    assert exc.value.code == "access_denied"


def test_cancel_from_paused_does_not_write(auth_db):
    user, _, engine = _user("owner@example.com")
    mission_id, _step_id = _authorized_marker(engine, user)
    engine.pause(user, mission_id)
    body = engine.request_cancel(user, mission_id)
    assert body["state"] == states.CANCELLED
    assert body["cancel_confirmed"] is True
    assert list(auth_db.rglob("marker.txt")) == []


def test_http_pause_resume_isolated(auth_db):
    owner, owner_token, engine = _user("owner@example.com")
    _other, other_token, _ = _user("intruder@example.com")
    mission_id, _step_id = _authorized_marker(engine, owner)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    denied = client.post(f"/api/sovereign/missions/{mission_id}/pause", headers={"Authorization": f"Bearer {other_token}"})
    assert denied.status_code == 403
    paused = client.post(f"/api/sovereign/missions/{mission_id}/pause", headers={"Authorization": f"Bearer {owner_token}"})
    assert paused.status_code == 200
    assert paused.json()["state"] == states.PAUSED
    resumed = client.post(f"/api/sovereign/missions/{mission_id}/resume", headers={"Authorization": f"Bearer {owner_token}"})
    assert resumed.json()["state"] == states.AUTHORIZED
