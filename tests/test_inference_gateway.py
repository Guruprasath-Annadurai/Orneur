from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread

import httpx
import pytest

from orca.auth.store import User
from orca.serve.inference import InferenceError, complete, history, reset_for_tests, set_history_path, stream_complete
from orca.serve.usage import reset_for_tests as reset_usage


def _user(uid: str) -> User:
    return User(id=uid, email=f"{uid}@example.com", name=uid, tier="free", verified=True)


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

    def _reply_text(self, prompt: str) -> str:
        if "what token" in prompt and "remember-alpha" in prompt:
            return "saw-alpha"
        if "remember-alpha" in prompt:
            return "stored"
        if "secret-from-a" in prompt:
            return "leaked" if "remember-alpha" in prompt else "isolated"
        return "pong"

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        req = json.loads(raw.decode() or "{}")
        prompt = req.get("prompt") or ""
        messages = req.get("messages") or []
        joined = prompt + " " + " ".join(m.get("content", "") for m in messages)
        if self.path.startswith("/api/generate") and req.get("stream"):
            chunks = [
                json.dumps({"model": "fixture-llama", "response": "pong-", "done": False}) + "\n",
                json.dumps({"model": "fixture-llama", "response": "ok", "done": True, "eval_count": 2, "prompt_eval_count": 3}) + "\n",
            ]
            body = "".join(chunks).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/api/chat"):
            text = self._reply_text(joined)
            if req.get("stream"):
                pieces = ["pong-", "ok"] if text == "pong" else [text]
                lines = []
                for i, piece in enumerate(pieces):
                    done = i == len(pieces) - 1
                    payload = {"model": "fixture-llama", "message": {"role": "assistant", "content": piece}, "done": done}
                    if done:
                        payload["eval_count"] = 2
                        payload["prompt_eval_count"] = 3
                    lines.append(json.dumps(payload) + "\n")
                body = "".join(lines).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self._send({"model": "fixture-llama", "message": {"role": "assistant", "content": text}, "done": True})
            return
        text = self._reply_text(joined)
        self._send(
            {
                "model": "fixture-llama",
                "response": text,
                "done": True,
                "prompt_eval_count": 4,
                "eval_count": 1,
            }
        )


@pytest.fixture()
def ollama_fixture(tmp_path):
    set_history_path(tmp_path / "turns.sqlite")
    reset_for_tests()
    reset_usage()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Ollama)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host = f"http://127.0.0.1:{server.server_address[1]}"
    yield host
    server.shutdown()
    set_history_path(None)


def test_authenticated_complete_uses_fixture_identity_not_native(ollama_fixture):
    result = complete(
        user=_user("user-a"),
        message="hello",
        model="fixture-llama",
        host=ollama_fixture,
        synthetic_provider=True,
    )
    assert result["text"] == "pong"
    assert result["backend"] == "ollama"
    assert result["model"] == "fixture-llama"
    assert result["identity"]["served_model"] == "fixture-llama"
    assert result["identity"]["backend"] == "ollama"
    assert result["live"] is False
    assert result["synthetic_provider"] is True
    assert result["native_family"] is None
    assert result["path"] == "/api/generate"
    assert "genesis" not in (result["model"] or "")
    assert result["tokens_out"] == 1


def test_history_is_per_user_and_second_turn_sees_context(ollama_fixture):
    complete(user=_user("user-a"), message="remember-alpha", model="fixture-llama", host=ollama_fixture, synthetic_provider=True)
    second = complete(user=_user("user-a"), message="what token?", model="fixture-llama", host=ollama_fixture, synthetic_provider=True)
    assert second["text"] == "saw-alpha"
    other = complete(user=_user("user-b"), message="secret-from-a", model="fixture-llama", host=ollama_fixture, synthetic_provider=True)
    assert other["text"] != "saw-alpha"
    assert all(row["content"] != "remember-alpha" for row in history("user-b"))


def test_stream_second_turn_sees_context(ollama_fixture):
    complete(user=_user("user-a"), message="remember-alpha", model="fixture-llama", host=ollama_fixture, synthetic_provider=True)
    streamed = stream_complete(
        user=_user("user-a"),
        message="what token?",
        model="fixture-llama",
        host=ollama_fixture,
        synthetic_provider=True,
    )
    assert streamed["text"] == "saw-alpha"
    assert streamed["path"] == "/api/chat"


def test_native_name_and_paid_backend_and_missing_user_are_refused(ollama_fixture):
    with pytest.raises(InferenceError) as exc:
        complete(user=_user("user-a"), message="hi", model="genesis", host=ollama_fixture, synthetic_provider=True)
    assert exc.value.code == "native_identity_refused"
    with pytest.raises(InferenceError) as exc:
        complete(user=_user("user-a"), message="hi", model="orneur-novus", host=ollama_fixture, synthetic_provider=True)
    assert exc.value.code == "native_identity_refused"
    with pytest.raises(InferenceError) as exc:
        complete(user="user-a", message="hi", model="fixture-llama", host=ollama_fixture, synthetic_provider=True)
    assert exc.value.code == "unauthenticated"
    from orca.serve.inference import refuse_paid

    with pytest.raises(InferenceError) as exc:
        refuse_paid(backend="openai")
    assert exc.value.code == "paid_backend_refused"


def test_stream_chunks_and_cooperative_cancel(ollama_fixture):
    body = stream_complete(
        user=_user("user-a"),
        message="hello",
        model="fixture-llama",
        host=ollama_fixture,
        synthetic_provider=True,
    )
    assert body["chunks"] == ["pong-", "ok"]
    assert body["text"] == "pong-ok"
    assert body["finish_reason"] == "stop"
    assert body["handlers_forcibly_stopped"] is False
    stop = Event()
    stop.set()
    cancelled = stream_complete(
        user=_user("user-a"),
        message="hello",
        model="fixture-llama",
        host=ollama_fixture,
        transport_stream=lambda host, model, msg: iter(["one", "two", "three"]),
        cancel=stop,
        synthetic_provider=True,
    )
    assert cancelled["cancelled"] is True
    assert cancelled["handlers_forcibly_stopped"] is False
    assert cancelled["text"] == ""


def test_unreachable_ollama_is_blocked_not_passed():
    set_history_path(Path("/tmp/orneur-inference-unreach.sqlite"))
    reset_for_tests()
    with pytest.raises(InferenceError) as exc:
        complete(user=_user("user-a"), message="hello", model="fixture-llama", host="http://127.0.0.1:1")
    assert exc.value.code == "provider_unavailable"
    set_history_path(None)


def _live_model_name() -> str | None:
    try:
        response = httpx.get("http://127.0.0.1:11434/api/tags", timeout=1.0)
        response.raise_for_status()
        names = [row.get("name") for row in response.json().get("models") or [] if row.get("name")]
    except Exception:
        return None
    return names[0] if names else None


def test_live_ollama_generate_or_block(tmp_path):
    name = _live_model_name()
    if not name:
        pytest.skip("BLOCKED: Ollama is not reachable on 127.0.0.1:11434 or has no installed model")
    set_history_path(tmp_path / "live.sqlite")
    reset_for_tests()
    result = complete(
        user=_user("user-a"),
        message="Reply with the single word pong.",
        model=name,
        host="http://127.0.0.1:11434",
    )
    assert result["live"] is True
    assert result["backend"] == "ollama"
    assert result["text"]
    assert result["path"] == "/api/generate"
    assert result["native_family"] is None
    assert "genesis" not in (result["model"] or "").lower()
    assert result["latency_ms"] > 0
    assert result["identity"]["served_model"]
    assert result["identity"]["backend"] == "ollama"


def test_live_ollama_chat_stream_and_next_turn_context(tmp_path):
    name = _live_model_name()
    if not name:
        pytest.skip("BLOCKED: Ollama is not reachable on 127.0.0.1:11434 or has no installed model")
    set_history_path(tmp_path / "live-stream.sqlite")
    reset_for_tests()
    first = complete(
        user=_user("user-a"),
        message="The secret token is ORNEUR-ALPHA.",
        model=name,
        host="http://127.0.0.1:11434",
    )
    assert first["live"] is True
    streamed = stream_complete(
        user=_user("user-a"),
        message="Repeat the secret token exactly.",
        model=name,
        host="http://127.0.0.1:11434",
    )
    assert streamed["live"] is True
    assert streamed["path"] == "/api/chat"
    assert streamed["chunks"]
    assert streamed["text"]
    assert streamed["handlers_forcibly_stopped"] is False
    assert streamed["native_family"] is None
    # Tiny models may ignore the instruction. Context must still be in the stored history.
    stored = history("user-a")
    assert any("ORNEUR-ALPHA" in row["content"] for row in stored)
    assert stored[-1]["role"] == "assistant"
    assert stored[-1]["content"] == streamed["text"]
