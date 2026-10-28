from __future__ import annotations

import json
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orca.auth.db import init_db
from orca.serve.inference import reset_for_tests
from orca.serve.inference_routes import router
from orca.sovereign_mission.service import SovereignMission


class _Ollama(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        return

    def _send(self, payload: dict, code=200):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/tags"):
            self._send({"models": [{"name": "fixture-llama"}]})
            return
        self._send({"error": "no"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        req = json.loads(raw.decode() or "{}")
        prompt = req.get("prompt") or ""
        messages = req.get("messages") or []
        joined = prompt + " " + " ".join(m.get("content", "") for m in messages)
        if "what token" in joined and "remember-alpha" in joined:
            text = "saw-alpha"
        elif "remember-alpha" in joined:
            text = "stored"
        elif "secret-from-a" in joined:
            text = "leaked" if "remember-alpha" in joined else "isolated"
        else:
            text = "pong"
        if self.path.startswith("/api/chat") and req.get("stream"):
            payload = {
                "model": "fixture-llama",
                "message": {"role": "assistant", "content": text},
                "done": True,
                "eval_count": 2,
                "prompt_eval_count": 3,
            }
            body = (json.dumps(payload) + "\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._send({"model": "fixture-llama", "response": text, "done": True, "eval_count": 1, "prompt_eval_count": 4})


@pytest.fixture()
def auth_db(isolated_home):
    init_db()
    reset_for_tests()
    yield isolated_home


@pytest.fixture()
def fixture_ollama():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Ollama)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host = f"http://127.0.0.1:{server.server_address[1]}"
    yield host
    server.shutdown()


def _sid() -> str:
    return uuid.uuid4().hex


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_http_inference_requires_auth_session_and_blocks_without_ollama(auth_db, monkeypatch):
    monkeypatch.setattr("orca.serve.inference_routes.CONFIG.ollama.host", "http://127.0.0.1:1")
    auth_db.create_user("owner@example.com", "correct-horse", "owner")
    token = SovereignMission().login("owner@example.com", "correct-horse")
    client = _client()
    anon = client.post("/api/inference/complete", json={"message": "hi", "model": "fixture-llama", "session_id": "s1"})
    assert anon.status_code == 401
    missing_session = client.post(
        "/api/inference/complete",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "hi", "model": "fixture-llama"},
    )
    assert missing_session.status_code == 422
    blocked = client.post(
        "/api/inference/complete",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "hi", "model": "fixture-llama", "session_id": "s1"},
    )
    assert blocked.status_code == 503
    assert blocked.json()["detail"]["code"] == "provider_unavailable"
    hist = client.get("/api/inference/history", headers={"Authorization": f"Bearer {token}"})
    assert hist.status_code == 422


def test_http_same_user_two_sessions_are_isolated(auth_db, fixture_ollama, monkeypatch):
    monkeypatch.setattr("orca.serve.inference_routes.CONFIG.ollama.host", fixture_ollama)
    auth_db.create_user("owner@example.com", "correct-horse", "owner")
    auth_db.create_user("other@example.com", "correct-horse", "other")
    owner = SovereignMission().login("owner@example.com", "correct-horse")
    other = SovereignMission().login("other@example.com", "correct-horse")
    client = _client()
    first = client.post(
        "/api/inference/complete",
        headers={"Authorization": f"Bearer {owner}"},
        json={"message": "remember-alpha", "model": "fixture-llama", "session_id": "conv-a"},
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["session_id"] == "conv-a"
    assert body["model"] == "fixture-llama"
    assert body["backend"] == "ollama"
    assert body["native_family"] is None
    assert "text" in body
    follow = client.post(
        "/api/inference/complete",
        headers={"Authorization": f"Bearer {owner}"},
        json={"message": "what token?", "model": "fixture-llama", "session_id": "conv-a"},
    )
    assert follow.status_code == 200
    assert follow.json()["text"] == "saw-alpha"
    other_conv = client.post(
        "/api/inference/complete",
        headers={"Authorization": f"Bearer {owner}"},
        json={"message": "secret-from-a", "model": "fixture-llama", "session_id": "conv-b"},
    )
    assert other_conv.status_code == 200
    assert other_conv.json()["text"] == "isolated"
    hist_a = client.get("/api/inference/history", params={"session_id": "conv-a"}, headers={"Authorization": f"Bearer {owner}"})
    hist_b = client.get("/api/inference/history", params={"session_id": "conv-b"}, headers={"Authorization": f"Bearer {owner}"})
    assert any(row["content"] == "remember-alpha" for row in hist_a.json()["messages"])
    assert all(row["content"] != "remember-alpha" for row in hist_b.json()["messages"])
    stolen = client.get("/api/inference/history", params={"session_id": "conv-a"}, headers={"Authorization": f"Bearer {other}"})
    assert stolen.status_code == 404
    native = client.post(
        "/api/inference/complete",
        headers={"Authorization": f"Bearer {owner}"},
        json={"message": "hi", "model": "genesis", "session_id": "conv-a"},
    )
    assert native.status_code == 409
    assert native.json()["detail"]["code"] == "native_identity_refused"


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
    auth_db.create_user("owner@example.com", "correct-horse", "owner")
    owner = SovereignMission().login("owner@example.com", "correct-horse")
    client = _client()
    model = names[0]
    sid_a, sid_b = _sid(), _sid()
    first = client.post(
        "/api/inference/complete",
        headers={"Authorization": f"Bearer {owner}"},
        json={"message": "Remember the codeword MAGENTA-42.", "model": model, "session_id": sid_a},
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["live"] is True
    assert body["backend"] == "ollama"
    assert body["native_family"] is None
    assert body["text"]
    hist = client.get(
        "/api/inference/history",
        params={"session_id": sid_a},
        headers={"Authorization": f"Bearer {owner}"},
    )
    assert hist.status_code == 200
    messages = hist.json()["messages"]
    assert any("MAGENTA-42" in row["content"] for row in messages)
    other = client.post(
        "/api/inference/complete",
        headers={"Authorization": f"Bearer {owner}"},
        json={"message": "What is the codeword?", "model": model, "session_id": sid_b},
    )
    assert other.status_code == 200
    other_hist = client.get(
        "/api/inference/history",
        params={"session_id": sid_b},
        headers={"Authorization": f"Bearer {owner}"},
    )
    assert all("MAGENTA-42" not in row["content"] for row in other_hist.json()["messages"])
    with client.stream(
        "POST",
        "/api/inference/stream",
        headers={"Authorization": f"Bearer {owner}"},
        json={"message": "Say one short sentence.", "model": model, "session_id": sid_a},
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
