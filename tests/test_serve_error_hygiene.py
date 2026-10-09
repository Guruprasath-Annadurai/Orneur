"""
Serve-layer error hygiene. A provider or library exception must never reach
the caller as text: upstream errors echo masked API keys, request ids and
file paths. The full exception is logged server-side under an error_id the
caller can quote to an operator.
"""
from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from orca.serve import api as api_module
from orca.serve.errors import public_error
from tests.test_api_chat_frontier_passthrough import _fake_cognitive_result, _fake_frontier_resolution

LEAK = "Incorrect API key provided: sk-" + "q" * 24 + " for org-ACME at /srv/orneur/secrets/key.pem"


@pytest.fixture
def client():
    return TestClient(api_module.app, raise_server_exceptions=False)


def _wire_failing_frontier(monkeypatch, exc):
    monkeypatch.setattr(api_module, "_resolve_backend_for_chat", lambda variant: _fake_frontier_resolution())

    def _raise(*_a, **_k):
        raise exc

    monkeypatch.setattr(api_module, "_generate_via_frontier_backend", _raise)
    monkeypatch.setattr(api_module, "check_input", lambda text: MagicMock(action="allow", flagged_categories=[]))
    monkeypatch.setattr(api_module, "_run_cognitive_kernel", _fake_cognitive_result)


def _sse(resp):
    return [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]


def _assert_no_leak(text: str):
    for fragment in ("sk-", "org-ACME", "/srv/orneur", "key.pem", "Incorrect API key"):
        assert fragment not in text


def test_chat_error_hides_upstream_text_and_logs_it(client, monkeypatch, caplog):
    _wire_failing_frontier(monkeypatch, RuntimeError(LEAK))
    with caplog.at_level(logging.ERROR, logger="orca.serve.errors"):
        resp = client.post("/api/chat", json={"message": "hi", "model_variant": "nano"})
    assert resp.status_code == 500
    body = resp.json()
    _assert_no_leak(resp.text)
    assert body["code"] == "backend_error"
    assert len(body["error_id"]) == 12
    # The operator can find the failure by the id the caller was given.
    record = next(r for r in caplog.records if body["error_id"] in r.getMessage())
    assert record.exc_info is not None
    assert LEAK in str(record.exc_info[1])


def test_stream_error_event_hides_upstream_text(client, monkeypatch):
    _wire_failing_frontier(monkeypatch, RuntimeError(LEAK))
    resp = client.post("/api/stream", json={"message": "hi", "model_variant": "nano"})
    assert resp.status_code == 200
    _assert_no_leak(resp.text)
    error = next(e for e in _sse(resp) if e["type"] == "error")
    assert error["code"] == "backend_error" and error["error_id"]


@pytest.mark.parametrize("exc, code", [
    (TimeoutError(LEAK), "upstream_timeout"),
    (ConnectionError(LEAK), "backend_unreachable"),
    (ValueError(LEAK), "backend_error"),
])
def test_error_codes_are_classified_without_exposing_text(client, monkeypatch, exc, code):
    _wire_failing_frontier(monkeypatch, exc)
    resp = client.post("/api/chat", json={"message": "hi", "model_variant": "nano"})
    _assert_no_leak(resp.text)
    assert resp.json()["code"] == code


def test_each_failure_gets_a_distinct_error_id():
    ids = {public_error(RuntimeError("x"), route="/t").error_id for _ in range(50)}
    assert len(ids) == 50


def test_public_error_never_includes_exception_text_even_when_overridden():
    err = public_error(RuntimeError(LEAK), route="/t", code="custom", message="Custom safe message.")
    assert err.code == "custom"
    _assert_no_leak(json.dumps(err.as_json()) + json.dumps(err.as_sse()))


def _upload(client, monkeypatch, exc):
    def _raise(filename, data):
        raise exc

    monkeypatch.setattr(api_module, "extract", _raise)
    return client.post("/api/docs/upload", files={"file": ("notes.txt", b"hello world", "text/plain")})


def test_document_extraction_keeps_user_fixable_errors_only(client, monkeypatch):
    resp = _upload(client, monkeypatch, ValueError("Unsupported file type: .xyz"))
    assert resp.status_code == 422
    assert "Unsupported file type: .xyz" in resp.json()["error"]


def test_document_extraction_hides_library_and_environment_errors(client, monkeypatch):
    for exc, code in ((RuntimeError(LEAK), "extraction_failed"), (ImportError(LEAK), "extractor_unavailable")):
        resp = _upload(client, monkeypatch, exc)
        assert resp.status_code == 422
        _assert_no_leak(resp.text)
        assert resp.json()["code"] == code
