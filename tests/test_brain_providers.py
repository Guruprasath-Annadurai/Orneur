"""
Tests for orca/brain/providers.py's OrcaBrain._resolve_model().

Covers a real, serious bug found via live load testing: Ollama's /api/tags
always returns tagged model names (e.g. "orca-nano:latest"), but a
configured/resolved model name is typically bare ("orca-nano"). The
original exact-match check meant EVERY real chat request failed with
"model not found" even when the exact model was listed — just under its
tagged name. This would have been a total production outage.
"""
from __future__ import annotations

import pytest

from orca.brain.providers import OrcaBrain


def _brain_with_available(monkeypatch, model, available):
    brain = OrcaBrain(model=model)
    monkeypatch.setattr(brain, "_list_available", lambda: available)
    return brain


def test_resolves_bare_name_against_tagged_ollama_listing(monkeypatch):
    """The exact bug: Ollama lists 'orca-nano:latest', caller requested the
    bare 'orca-nano' — must resolve successfully, not raise."""
    brain = _brain_with_available(monkeypatch, "orca-nano", ["orca-nano:latest", "qwen2.5:7b-instruct"])
    assert brain.model == "orca-nano"


def test_resolves_when_bare_name_is_listed_directly(monkeypatch):
    brain = _brain_with_available(monkeypatch, "orca-nano", ["orca-nano", "qwen2.5:7b-instruct"])
    assert brain.model == "orca-nano"


def test_raises_when_model_genuinely_not_installed(monkeypatch):
    brain = _brain_with_available(monkeypatch, "orca-ultra", ["orca-nano:latest", "orca-core:latest"])
    with pytest.raises(RuntimeError, match="not found in Ollama"):
        _ = brain.model


def test_does_not_falsely_match_a_different_model_with_shared_prefix(monkeypatch):
    """'orca-nano' must not match 'orca-nano-v7:latest' — only its own exact
    bare or tagged form."""
    brain = _brain_with_available(monkeypatch, "orca-nano", ["orca-nano-v7:latest", "orca-core-v2:latest"])
    with pytest.raises(RuntimeError, match="not found in Ollama"):
        _ = brain.model


def test_explicit_model_with_tag_already_included_still_works(monkeypatch):
    brain = _brain_with_available(monkeypatch, "orca-nano:latest", ["orca-nano:latest"])
    assert brain.model == "orca-nano:latest"


# ── complete()/stream() timeout + retry robustness ──────────────────────────
#
# Real problem this covers: OrcaBrain.complete()/stream() previously caught
# ONLY httpx.ConnectError — a real request timeout under load propagated as
# an unhandled exception straight to the caller, with zero retry. A live
# investigation found 34% of generation calls timing out under sustained
# load in a related eval harness at a SHORTER timeout than this path uses —
# meaning this exact failure mode is real and reachable in production chat,
# not hypothetical.

import httpx
from unittest.mock import MagicMock, patch


def _brain(monkeypatch):
    brain = OrcaBrain(model="orca-core")
    monkeypatch.setattr(brain, "_resolve_model", lambda: "orca-core")
    return brain


def test_complete_retries_once_on_timeout_before_giving_up(monkeypatch):
    brain = _brain(monkeypatch)
    calls = {"n": 0}

    def _fake_post(url, json, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ReadTimeout("simulated timeout")
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"message": {"content": "a real answer"}}
        return resp

    with patch("httpx.post", side_effect=_fake_post):
        result = brain.complete([{"role": "user", "content": "hi"}])

    assert calls["n"] == 2
    assert result == "a real answer"


def test_complete_raises_clear_error_after_exhausting_retries(monkeypatch):
    brain = _brain(monkeypatch)

    def _always_times_out(url, json, timeout):
        raise httpx.ReadTimeout("simulated persistent timeout")

    with patch("httpx.post", side_effect=_always_times_out):
        with pytest.raises(RuntimeError, match="timed out after 2 attempt"):
            brain.complete([{"role": "user", "content": "hi"}], retries=1)


def test_complete_still_raises_immediately_on_connect_error(monkeypatch):
    """ConnectError (Ollama not running at all) should never be retried —
    it's not a transient load issue, it's a hard failure."""
    brain = _brain(monkeypatch)
    calls = {"n": 0}

    def _fake_post(url, json, timeout):
        calls["n"] += 1
        raise httpx.ConnectError("simulated connection refused")

    with patch("httpx.post", side_effect=_fake_post):
        with pytest.raises(RuntimeError, match="Ollama disconnected"):
            brain.complete([{"role": "user", "content": "hi"}], retries=1)

    assert calls["n"] == 1  # no retry attempted for a connection failure
