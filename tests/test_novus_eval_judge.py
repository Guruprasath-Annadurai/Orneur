"""
Tests for NovusEvaluator.run_with_judge() — the judge-mode scoring path
added after a spot-check found keyword-overlap scoring gave a 0.0 to a
genuinely well-reasoned live answer purely because it used different
vocabulary than the fixed keyword list (see orca/train/novus_eval.py's
module docstring on run_with_judge).
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from orca.train import novus_eval as novus_eval_module
from orca.train.novus_eval import NovusEvaluator


@pytest.fixture(autouse=True)
def _isolate_eval_dir(tmp_path, monkeypatch):
    """
    Real bug this fixes: run_with_judge() writes its report directly to
    EVAL_DIR (not via a separate save step), and these tests use
    model="orca-core" — the actual production model name. Without this
    isolation, every test-suite run was silently overwriting the real,
    live judge-scored novus_eval_judged_orca-core.json (88.1% overall)
    with mocked test fixture data (0.5-0.85 depending on which test ran
    last) — discovered when a model-card regeneration showed 50% instead
    of the real 88.1% right after a full suite run.
    """
    monkeypatch.setattr(novus_eval_module, "EVAL_DIR", tmp_path)


def _fake_urlopen_factory(generate_response: str, judge_payload: dict):
    """Returns a fake urlopen that answers /api/generate calls with
    generate_response, and judge calls (system prompt present) with
    judge_payload serialized as the judge model's raw text output."""

    class _FakeResp:
        def __init__(self, body: bytes):
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _fake_urlopen(req, timeout=30):
        body = json.loads(req.data.decode())
        if "system" in body:  # this is the judge call
            raw = json.dumps(judge_payload)
            return _FakeResp(json.dumps({"response": raw}).encode())
        return _FakeResp(json.dumps({"response": generate_response}).encode())

    return _fake_urlopen


def test_run_with_judge_scores_using_judge_not_keywords():
    evaluator = NovusEvaluator(model="orca-core")
    fake = _fake_urlopen_factory(
        generate_response="A well-reasoned framework using different words than the keyword list.",
        judge_payload={"score": 0.85, "reason": "Covers the real trade-offs clearly."},
    )
    with patch("urllib.request.urlopen", fake):
        report = evaluator.run_with_judge("llama3.1:8b", n=2)

    assert report["eval_set"] == "novus_v1_judged"
    assert report["judge_model"] == "llama3.1:8b"
    assert report["n_prompts"] == 2
    for r in report["results"]:
        assert r["judged_score"] == 0.85
        assert "keyword_hits" not in r  # judge mode doesn't use keyword scoring at all
    assert report["overall_score"] == 0.85


def test_run_with_judge_computes_per_domain_breakdown():
    evaluator = NovusEvaluator(model="orca-core")
    fake = _fake_urlopen_factory(
        generate_response="Some response.",
        judge_payload={"score": 0.6, "reason": "Reasonable."},
    )
    with patch("urllib.request.urlopen", fake):
        report = evaluator.run_with_judge("llama3.1:8b", n=3)

    assert "engineering" in report["domain_scores"]
    assert report["domain_scores"]["engineering"] == 0.6


def test_run_with_judge_falls_back_gracefully_on_judge_parse_failure():
    evaluator = NovusEvaluator(model="orca-core")

    class _FakeResp:
        def __init__(self, body):
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _fake_urlopen(req, timeout=30):
        body = json.loads(req.data.decode())
        if "system" in body:
            return _FakeResp(json.dumps({"response": "not valid json at all"}).encode())
        return _FakeResp(json.dumps({"response": "some answer"}).encode())

    with patch("urllib.request.urlopen", _fake_urlopen):
        report = evaluator.run_with_judge("llama3.1:8b", n=1)

    # Falls back to a neutral 0.5 rather than crashing the whole eval run.
    assert report["results"][0]["judged_score"] == 0.5
    assert "judge error" in report["results"][0]["judge_reason"]


# ── trials averaging — added after 3 independent live runs of the SAME ─────
# unchanged model showed 88.1%, 71.3%, and other swings in between; a
# single trial is not a trustworthy number for this eval.

def test_default_trials_is_one_backward_compatible():
    evaluator = NovusEvaluator(model="orca-core")
    fake = _fake_urlopen_factory(
        generate_response="An answer.",
        judge_payload={"score": 0.7, "reason": "fine"},
    )
    with patch("urllib.request.urlopen", fake):
        report = evaluator.run_with_judge("llama3.1:8b", n=1)

    assert report["trials_per_prompt"] == 1
    assert report["results"][0]["trials"] == 1
    assert report["results"][0]["trial_scores"] == [0.7]


def test_trials_averages_across_regenerated_samples():
    """Real behavior this covers: each trial re-generates AND re-judges,
    and the final score is the average across trials — not just the last
    one or the first one."""
    evaluator = NovusEvaluator(model="orca-core")
    call_count = {"judge": 0}

    class _FakeResp:
        def __init__(self, body):
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _fake_urlopen(req, timeout=30):
        body = json.loads(req.data.decode())
        if "system" in body:
            call_count["judge"] += 1
            # Alternate 1.0 / 0.0 across trials -> averages to 0.5 for
            # any even number of trials.
            score = 1.0 if call_count["judge"] % 2 == 1 else 0.0
            return _FakeResp(json.dumps({"response": json.dumps({"score": score, "reason": "x"})}).encode())
        return _FakeResp(json.dumps({"response": "an answer"}).encode())

    with patch("urllib.request.urlopen", _fake_urlopen):
        report = evaluator.run_with_judge("llama3.1:8b", n=1, trials=2)

    assert report["trials_per_prompt"] == 2
    assert report["results"][0]["trials"] == 2
    assert report["results"][0]["trial_scores"] == [1.0, 0.0]
    assert report["results"][0]["judged_score"] == 0.5


def test_trials_regenerates_response_each_time_not_just_rejudges_same_one():
    """Real property: trials must call _generate() again each time, not
    judge the same cached response repeatedly — matching the real
    variance source (generation is nondeterministic at temperature=0.4,
    not just judge scoring)."""
    evaluator = NovusEvaluator(model="orca-core")
    generate_call_count = {"n": 0}

    class _FakeResp:
        def __init__(self, body):
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _fake_urlopen(req, timeout=30):
        body = json.loads(req.data.decode())
        if "system" in body:
            return _FakeResp(json.dumps({"response": json.dumps({"score": 0.8, "reason": "x"})}).encode())
        generate_call_count["n"] += 1
        return _FakeResp(json.dumps({"response": f"answer number {generate_call_count['n']}"}).encode())

    with patch("urllib.request.urlopen", _fake_urlopen):
        report = evaluator.run_with_judge("llama3.1:8b", n=1, trials=3)

    assert generate_call_count["n"] == 3  # one real generation per trial, not one cached response reused
    assert report["results"][0]["response"] == "answer number 3"  # last trial's response is what's saved
