"""
Tests for orca/train/eval.py's OllamaEvaluator.compare_with_judge().

Covers the real problem this fixes: compare() (keyword-overlap scoring on
GOLDEN_EVALS, a CS/algorithms-heavy set) gave a near-meaningless result on
a real orca-nano vs orca-core-v1 run — 19/20 ties, both near 0% — because
neither tier's actual training domains overlap with that benchmark well.
compare_with_judge() uses a domain-neutral shared prompt set and an LLM
judge instead of keyword matching.
"""
from __future__ import annotations

import json
import urllib.request

import pytest

from orca.train.eval import OllamaEvaluator, SHARED_TIER_EVALS


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_uses_shared_tier_evals_not_golden_evals(monkeypatch):
    seen_prompts = []

    def _fake_urlopen(req, timeout=60):
        body = json.loads(req.data)
        if "winner" in body.get("prompt", ""):
            return _FakeResponse({"response": '{"winner": "tie", "reason": "equally good"}'})
        seen_prompts.append(body["prompt"])
        return _FakeResponse({"response": "a generated response"})

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    result = OllamaEvaluator.compare_with_judge("model-a", "model-b", judge_model="judge-model", n=3)

    assert result["n_prompts"] == 3
    for prompt in seen_prompts:
        assert prompt in {item["prompt"] for item in SHARED_TIER_EVALS}


def test_tallies_wins_and_ties_correctly(monkeypatch):
    verdicts = iter(["A", "B", "tie"])

    def _fake_urlopen(req, timeout=60):
        body = json.loads(req.data)
        if '"winner"' in body["prompt"]:
            return _FakeResponse({"response": json.dumps({"winner": next(verdicts), "reason": "because"})})
        return _FakeResponse({"response": "a generated response"})

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    result = OllamaEvaluator.compare_with_judge("model-a", "model-b", judge_model="judge-model", n=3)

    assert result["wins_a"] == 1
    assert result["wins_b"] == 1
    assert result["ties"] == 1
    assert result["winner"] == "tie"  # 1-1 tie overall


def test_judge_failure_defaults_to_tie(monkeypatch):
    def _fake_urlopen(req, timeout=60):
        body = json.loads(req.data)
        if '"winner"' in body["prompt"]:
            raise ConnectionError("judge unreachable")
        return _FakeResponse({"response": "a generated response"})

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    result = OllamaEvaluator.compare_with_judge("model-a", "model-b", judge_model="judge-model", n=2)

    assert all(r["winner"] == "tie" for r in result["results"])
    assert result["ties"] == 2


def test_n_none_uses_full_shared_eval_set(monkeypatch):
    def _fake_urlopen(req, timeout=60):
        body = json.loads(req.data)
        if '"winner"' in body["prompt"]:
            return _FakeResponse({"response": '{"winner": "tie", "reason": "ok"}'})
        return _FakeResponse({"response": "a generated response"})

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    result = OllamaEvaluator.compare_with_judge("model-a", "model-b", judge_model="judge-model")

    assert result["n_prompts"] == len(SHARED_TIER_EVALS)
