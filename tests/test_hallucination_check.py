"""
Tests for orca/docs/hallucination_check.py's check_grounding() — the
semantic contradiction detector, complementary to citation_check.py's
marker-presence checking. Covers: no-context trivial pass, grounded/
contradicted verdicts, judge-error fail-open behavior, and retry-on-
timeout (mirroring the pattern already established this session for every
other judge-mode check).
"""
from __future__ import annotations

import json
from unittest.mock import patch

from orca.docs.hallucination_check import check_grounding


def _fake_urlopen(judge_payload: dict):
    class _FakeResp:
        def __init__(self, body: bytes):
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _fake(req, timeout=60):
        return _FakeResp(json.dumps({"response": json.dumps(judge_payload)}).encode())

    return _fake


def test_no_context_is_trivially_grounded():
    result = check_grounding("Some response.", "", judge_model="llama3.1:8b")
    assert result["had_context"] is False
    assert result["grounded"] is True
    assert result["confidence"] == 1.0


def test_grounded_response_reports_grounded_true():
    fake = _fake_urlopen({"grounded": True, "confidence": 0.95, "issues": [], "reason": "Fully supported by context."})
    with patch("urllib.request.urlopen", fake):
        result = check_grounding("The sky is blue.", "The sky appears blue due to Rayleigh scattering.", "llama3.1:8b")

    assert result["had_context"] is True
    assert result["grounded"] is True
    assert result["confidence"] == 0.95
    assert result["issues"] == []


def test_contradicted_response_reports_grounded_false_with_issues():
    fake = _fake_urlopen({
        "grounded": False, "confidence": 0.9,
        "issues": ["Response claims the company was founded in 2010, context says 2015."],
        "reason": "Contains a fabricated date contradicting the source.",
    })
    with patch("urllib.request.urlopen", fake):
        result = check_grounding(
            "The company was founded in 2010.",
            "The company was founded in 2015 by three engineers.",
            "llama3.1:8b",
        )

    assert result["grounded"] is False
    assert len(result["issues"]) == 1
    assert "2010" in result["issues"][0]


def test_legitimate_inference_is_not_flagged_when_judge_says_so():
    """The judge is instructed not to flag reasonable synthesis — this
    test just confirms the plumbing respects whatever verdict the judge
    actually returns, since the judge prompt itself carries that nuance."""
    fake = _fake_urlopen({
        "grounded": True, "confidence": 0.8, "issues": [],
        "reason": "Reasonable summary of the context, not a fabrication.",
    })
    with patch("urllib.request.urlopen", fake):
        result = check_grounding("In short, the approach favors reliability over speed.", "Long context...", "llama3.1:8b")

    assert result["grounded"] is True


def test_fails_open_on_judge_parse_failure():
    class _FakeResp:
        def read(self):
            return json.dumps({"response": "not valid json"}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    with patch("urllib.request.urlopen", lambda req, timeout=60: _FakeResp()):
        result = check_grounding("Some response.", "Some context.", "llama3.1:8b", retries=0)

    # Fails OPEN (grounded=True) rather than flagging every response when
    # the judge itself is broken — a broken judge should degrade to
    # "unknown," not manufacture false hallucination alarms.
    assert result["grounded"] is True
    assert result["confidence"] == 0.0
    assert "judge error" in result["reason"]


def test_retries_once_on_timeout_before_failing_open():
    calls = {"n": 0}

    class _FakeResp:
        def read(self):
            return json.dumps({"response": json.dumps({"grounded": True, "confidence": 0.7, "issues": [], "reason": "ok"})}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _fake_urlopen(req, timeout=60):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("simulated timeout")
        return _FakeResp()

    with patch("urllib.request.urlopen", _fake_urlopen):
        result = check_grounding("Some response.", "Some context.", "llama3.1:8b")

    assert calls["n"] == 2
    assert result["grounded"] is True
    assert result["confidence"] == 0.7
