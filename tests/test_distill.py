"""
Tests for orca/train/distill.py's Nvidia-teacher retry/backoff logic.

Real bug this covers: the original unthrottled implementation had no retry
at all — a single 429 was a hard failure, and since nothing slowed the
request rate down, one rate-limit hit cascaded into ~290 consecutive dead
attempts in production (see the overnight distillation run). These tests
lock in that a 429/5xx is retried with backoff and only surfaces as a real
failure once retries are exhausted, while a non-transient error (e.g. 401)
is never retried.
"""
from __future__ import annotations

import httpx
import pytest
from openai import APIStatusError

from orca.train import distill


def _status_error(status_code: int, headers: dict | None = None) -> APIStatusError:
    request = httpx.Request("POST", "https://integrate.api.nvidia.com/v1/chat/completions")
    response = httpx.Response(status_code, request=request, json={"status": status_code}, headers=headers or {})
    return APIStatusError(f"Error code: {status_code}", response=response, body=None)


class _FakeCompletions:
    def __init__(self, side_effects):
        self._side_effects = list(side_effects)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        effect = self._side_effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return effect


class _FakeChat:
    def __init__(self, completions):
        self.completions = completions


class _FakeClient:
    def __init__(self, side_effects):
        self.chat = _FakeChat(_FakeCompletions(side_effects))


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeCompletion:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    # Backoff sleeps for real seconds (8/16/32/...) — tests must not actually wait.
    monkeypatch.setattr(distill.time, "sleep", lambda seconds: None)


@pytest.fixture
def _api_key(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key-not-real")


def test_429_retried_then_succeeds(monkeypatch, _api_key):
    fake_client = _FakeClient([_status_error(429), _status_error(429), _FakeCompletion("real answer")])
    import openai
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: fake_client)

    logs = []
    result = distill._nvidia_teacher_generate(
        "prompt", "nvidia/nemotron-3-ultra-550b-a55b", 700, on_log=logs.append
    )

    assert result == "real answer"
    assert fake_client.chat.completions.calls == 3
    assert sum("waiting" in m for m in logs) == 2


def test_5xx_retried_same_as_429(monkeypatch, _api_key):
    fake_client = _FakeClient([_status_error(503), _FakeCompletion("ok")])
    import openai
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: fake_client)

    result = distill._nvidia_teacher_generate("prompt", "nvidia/x", 700)
    assert result == "ok"
    assert fake_client.chat.completions.calls == 2


def test_non_transient_error_raised_immediately_no_retry(monkeypatch, _api_key):
    fake_client = _FakeClient([_status_error(401)])
    import openai
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: fake_client)

    with pytest.raises(APIStatusError):
        distill._nvidia_teacher_generate("prompt", "nvidia/x", 700)

    assert fake_client.chat.completions.calls == 1  # no retry wasted on a non-transient error


def test_retries_exhausted_raises_last_error(monkeypatch, _api_key):
    fake_client = _FakeClient([_status_error(429)] * distill._CLOUD_MAX_RETRIES)
    import openai
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: fake_client)

    with pytest.raises(APIStatusError) as exc_info:
        distill._nvidia_teacher_generate("prompt", "nvidia/x", 700)

    assert exc_info.value.status_code == 429
    assert fake_client.chat.completions.calls == distill._CLOUD_MAX_RETRIES


def test_retry_after_header_overrides_exponential_backoff(monkeypatch, _api_key):
    fake_client = _FakeClient([_status_error(429, headers={"retry-after": "3"}), _FakeCompletion("ok")])
    import openai
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: fake_client)

    sleeps = []
    monkeypatch.setattr(distill.time, "sleep", lambda s: sleeps.append(s))

    logs = []
    result = distill._nvidia_teacher_generate(
        "prompt", "nvidia/x", 700, on_log=logs.append
    )

    assert result == "ok"
    assert sleeps == [3.0]  # honored the server's Retry-After, not the 8s exponential guess
    assert any("Retry-After header" in m for m in logs)


def test_no_retry_after_header_falls_back_to_exponential(monkeypatch, _api_key):
    fake_client = _FakeClient([_status_error(429), _FakeCompletion("ok")])  # no headers
    import openai
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: fake_client)

    sleeps = []
    monkeypatch.setattr(distill.time, "sleep", lambda s: sleeps.append(s))

    logs = []
    distill._nvidia_teacher_generate("prompt", "nvidia/x", 700, on_log=logs.append)

    assert sleeps == [distill._CLOUD_BASE_BACKOFF]  # first-attempt exponential value
    assert any("exponential backoff" in m for m in logs)


def test_missing_api_key_raises_clear_error(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="NVIDIA_API_KEY not set"):
        distill._nvidia_teacher_generate("prompt", "nvidia/x", 700)


def test_openrouter_backend_uses_openrouter_key_and_base_url(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    fake_client = _FakeClient([_FakeCompletion("via openrouter")])

    captured = {}
    import openai

    def fake_openai(**kw):
        captured.update(kw)
        return fake_client

    monkeypatch.setattr(openai, "OpenAI", fake_openai)

    result = distill._openrouter_teacher_generate("prompt", "nvidia/nemotron-3-ultra-550b-a55b", 700)

    assert result == "via openrouter"
    assert captured["base_url"] == distill.OPENROUTER_API_BASE
    assert captured["api_key"] == "test-openrouter-key"


def test_openrouter_missing_key_raises_clear_error(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY not set"):
        distill._openrouter_teacher_generate("prompt", "nvidia/x", 700)


def test_teacher_generate_backend_openrouter_forces_openrouter_even_for_nvidia_model_id(monkeypatch):
    # Same 'nvidia/...' model id string is used by both providers — backend
    # choice must come from the explicit teacher_backend arg, not be guessed
    # from the model name, since that string alone is ambiguous between them.
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    calls = []
    monkeypatch.setattr(
        distill, "_openrouter_teacher_generate",
        lambda *a, **kw: calls.append("openrouter") or "ok"
    )
    monkeypatch.setattr(
        distill, "_nvidia_teacher_generate",
        lambda *a, **kw: calls.append("nvidia") or "ok"
    )

    result = distill._teacher_generate(
        "prompt", "nvidia/nemotron-3-ultra-550b-a55b", "http://localhost:11434",
        teacher_backend="openrouter",
    )

    assert result == "ok"
    assert calls == ["openrouter"]


def test_teacher_generate_backend_auto_still_uses_nvidia_direct(monkeypatch):
    calls = []
    monkeypatch.setattr(
        distill, "_openrouter_teacher_generate",
        lambda *a, **kw: calls.append("openrouter") or "ok"
    )
    monkeypatch.setattr(
        distill, "_nvidia_teacher_generate",
        lambda *a, **kw: calls.append("nvidia") or "ok"
    )

    distill._teacher_generate(
        "prompt", "nvidia/nemotron-3-ultra-550b-a55b", "http://localhost:11434",
        teacher_backend="auto",
    )

    assert calls == ["nvidia"]  # unchanged default behavior
