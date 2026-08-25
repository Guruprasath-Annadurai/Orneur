"""
Tests that OllamaEvaluator.accuracy_eval() persists the actual response
text alongside each score. Real gap this closes: a 0%-scored prompt was
previously unauditable after the fact — investigating a real core (Novus)
finding (a genuinely well-reasoned live answer scoring 0.0 purely from
missing exact keywords) required re-generating a brand new, nondeterministic
sample rather than inspecting what was actually scored.
"""
from __future__ import annotations

import json
from unittest.mock import patch

from orca.train.eval import OllamaEvaluator


def _fake_urlopen(response_text: str):
    class _FakeResp:
        def __init__(self, body: bytes):
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _fake(req, timeout=30):
        return _FakeResp(json.dumps({"response": response_text}).encode())

    return _fake


def test_accuracy_eval_persists_full_response_text():
    evaluator = OllamaEvaluator(model="orca-core")
    with patch("urllib.request.urlopen", _fake_urlopen("A genuinely reasoned answer with different wording.")):
        report = evaluator.accuracy_eval(n=2)

    for r in report["results"]:
        assert "response" in r
        assert r["response"] == "A genuinely reasoned answer with different wording."


def test_accuracy_eval_truncates_very_long_responses():
    long_text = "x" * 2000
    evaluator = OllamaEvaluator(model="orca-core")
    with patch("urllib.request.urlopen", _fake_urlopen(long_text)):
        report = evaluator.accuracy_eval(n=1)

    assert len(report["results"][0]["response"]) == 500
