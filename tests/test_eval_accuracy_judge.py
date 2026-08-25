"""
Tests for OllamaEvaluator.accuracy_eval_with_judge() — judge-mode scoring
for the generic golden eval set, added after a live investigation found
core scoring 0.0-0.4 on 9 prompts (Dijkstra, float comparison, N+1 queries,
circuit breakers, webhooks, XSS, timing attacks) where the saved response
text was, on manual read, genuinely correct every time — the keyword list
just didn't match the model's actual vocabulary. Same fix already applied
to orca/train/novus_eval.py's business-domain eval.

IMPORTANT: these tests never call full_report() with a real model name,
since full_report() writes directly to the real EVAL_DIR — a prior bug in
this test suite (test_novus_eval_judge.py before it was fixed) silently
overwrote real production eval data by not isolating this. Tests here call
accuracy_eval_with_judge() directly, which does NOT write to disk itself.
"""
from __future__ import annotations

import json
from unittest.mock import patch

from orca.train.eval import OllamaEvaluator


def _fake_urlopen_factory(generate_response: str, judge_payload: dict):
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
        if "system" in body and "grading a technical response" in body["system"]:
            return _FakeResp(json.dumps({"response": json.dumps(judge_payload)}).encode())
        return _FakeResp(json.dumps({"response": generate_response}).encode())

    return _fake_urlopen


def test_accuracy_eval_with_judge_scores_using_judge_not_keywords():
    evaluator = OllamaEvaluator(model="test-model")
    fake = _fake_urlopen_factory(
        generate_response="A correct answer phrased differently than the keyword list expects.",
        judge_payload={"score": 0.9, "reason": "Correct and complete."},
    )
    with patch("urllib.request.urlopen", fake):
        report = evaluator.accuracy_eval_with_judge("llama3.1:8b", n=3)

    assert report["judge_model"] == "llama3.1:8b"
    assert report["accuracy"] == 0.9
    assert report["n_prompts"] == 3
    for r in report["results"]:
        assert "judged_score" in r
        assert "keyword_score" not in r  # judge mode doesn't use keyword scoring at all
        assert "response" in r


def test_accuracy_eval_with_judge_persists_response_text():
    evaluator = OllamaEvaluator(model="test-model")
    long_response = "x" * 800
    fake = _fake_urlopen_factory(
        generate_response=long_response,
        judge_payload={"score": 0.7, "reason": "Mostly right."},
    )
    with patch("urllib.request.urlopen", fake):
        report = evaluator.accuracy_eval_with_judge("llama3.1:8b", n=1)

    assert len(report["results"][0]["response"]) == 500


def test_accuracy_eval_with_judge_falls_back_gracefully_on_parse_failure():
    evaluator = OllamaEvaluator(model="test-model")
    fake = _fake_urlopen_factory(
        generate_response="some answer",
        judge_payload=None,  # will be serialized as "null" -> not a dict with .get, forces exception path differently
    )

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
        if "system" in body and "grading a technical response" in body["system"]:
            return _FakeResp(json.dumps({"response": "not valid json"}).encode())
        return _FakeResp(json.dumps({"response": "some answer"}).encode())

    with patch("urllib.request.urlopen", _fake_urlopen):
        report = evaluator.accuracy_eval_with_judge("llama3.1:8b", n=1)

    assert report["results"][0]["judged_score"] == 0.5
    assert "judge error" in report["results"][0]["judge_reason"]


def test_full_report_uses_judge_accuracy_when_accuracy_judge_model_given(monkeypatch, tmp_path):
    from orca.train import eval as eval_module
    monkeypatch.setattr(eval_module, "EVAL_DIR", tmp_path)  # isolate the disk write full_report() does

    evaluator = OllamaEvaluator(model="test-model")
    called = {"judge": False, "keyword": False}

    monkeypatch.setattr(evaluator, "benchmark_speed", lambda: {"tokens_per_sec": 10.0})
    monkeypatch.setattr(evaluator, "style_eval", lambda n=10: {"style_score": 7.0, "n_samples": n, "scores": []})

    def _fake_judge(judge_model, n=None, trials=1):
        called["judge"] = True
        return {"accuracy": 0.85, "judge_model": judge_model, "trials_per_prompt": trials, "results": [], "n_prompts": 5}

    def _fake_keyword(n=None):
        called["keyword"] = True
        return {"accuracy": 0.5, "results": [], "n_prompts": 5}

    monkeypatch.setattr(evaluator, "accuracy_eval_with_judge", _fake_judge)
    monkeypatch.setattr(evaluator, "accuracy_eval", _fake_keyword)

    report = evaluator.full_report(accuracy_judge_model="llama3.1:8b")

    assert called["judge"] is True
    assert called["keyword"] is False
    assert report["accuracy"]["accuracy"] == 0.85


def test_full_report_uses_keyword_accuracy_when_no_judge_model_given(monkeypatch, tmp_path):
    from orca.train import eval as eval_module
    monkeypatch.setattr(eval_module, "EVAL_DIR", tmp_path)

    evaluator = OllamaEvaluator(model="test-model")
    called = {"judge": False, "keyword": False}

    monkeypatch.setattr(evaluator, "benchmark_speed", lambda: {"tokens_per_sec": 10.0})
    monkeypatch.setattr(evaluator, "style_eval", lambda n=10: {"style_score": 7.0, "n_samples": n, "scores": []})

    def _fake_judge(judge_model, n=None):
        called["judge"] = True
        return {}

    def _fake_keyword(n=None):
        called["keyword"] = True
        return {"accuracy": 0.5, "results": [], "n_prompts": 5}

    monkeypatch.setattr(evaluator, "accuracy_eval_with_judge", _fake_judge)
    monkeypatch.setattr(evaluator, "accuracy_eval", _fake_keyword)

    report = evaluator.full_report()

    assert called["keyword"] is True
    assert called["judge"] is False


def test_generate_retries_once_on_timeout_before_giving_up():
    """
    Real gap this closes: a live run found 34% of generation calls timing
    out at the previous 60s limit with no retry, silently poisoning the
    accuracy number with judge-scored-0.0 non-answers.
    """
    evaluator = OllamaEvaluator(model="test-model")
    calls = {"n": 0}

    def _fake_urlopen(req, timeout=60):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("simulated timeout on first attempt")

        class _FakeResp:
            def read(self):
                return json.dumps({"response": "a real answer"}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return _FakeResp()

    with patch("urllib.request.urlopen", _fake_urlopen):
        result = evaluator._generate("some prompt")

    assert calls["n"] == 2
    assert result == "a real answer"


def test_generate_falls_back_to_error_string_after_exhausting_retries():
    evaluator = OllamaEvaluator(model="test-model")

    def _always_times_out(req, timeout=60):
        raise TimeoutError("simulated persistent timeout")

    with patch("urllib.request.urlopen", _always_times_out):
        result = evaluator._generate("some prompt", retries=1)

    assert "error after 2 attempt(s)" in result


# ── trials averaging — added after a single run of the SAME unchanged ──────
# model showed 61.6% (timeout-corrupted) then 93.1% on a later run; even
# with the timeout bug fixed, a single sample is one draw from a
# nondeterministic (temperature=0.7) generation.

def test_accuracy_eval_with_judge_default_trials_is_one():
    evaluator = OllamaEvaluator(model="test-model")
    fake = _fake_urlopen_factory(
        generate_response="An answer.",
        judge_payload={"score": 0.6, "reason": "fine"},
    )
    with patch("urllib.request.urlopen", fake):
        report = evaluator.accuracy_eval_with_judge("llama3.1:8b", n=1)

    assert report["trials_per_prompt"] == 1
    assert report["results"][0]["trials"] == 1
    assert report["results"][0]["trial_scores"] == [0.6]


def test_accuracy_eval_with_judge_averages_across_trials():
    evaluator = OllamaEvaluator(model="test-model")
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
        if "system" in body and "grading a technical response" in body["system"]:
            call_count["judge"] += 1
            score = 1.0 if call_count["judge"] % 2 == 1 else 0.0
            return _FakeResp(json.dumps({"response": json.dumps({"score": score, "reason": "x"})}).encode())
        return _FakeResp(json.dumps({"response": "an answer"}).encode())

    with patch("urllib.request.urlopen", _fake_urlopen):
        report = evaluator.accuracy_eval_with_judge("llama3.1:8b", n=1, trials=2)

    assert report["trials_per_prompt"] == 2
    assert report["results"][0]["trial_scores"] == [1.0, 0.0]
    assert report["results"][0]["judged_score"] == 0.5


def test_accuracy_eval_with_judge_regenerates_each_trial():
    evaluator = OllamaEvaluator(model="test-model")
    generate_count = {"n": 0}

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
        if "system" in body and "grading a technical response" in body["system"]:
            return _FakeResp(json.dumps({"response": json.dumps({"score": 0.7, "reason": "x"})}).encode())
        generate_count["n"] += 1
        return _FakeResp(json.dumps({"response": f"answer {generate_count['n']}"}).encode())

    with patch("urllib.request.urlopen", _fake_urlopen):
        report = evaluator.accuracy_eval_with_judge("llama3.1:8b", n=1, trials=3)

    assert generate_count["n"] == 3
    assert report["results"][0]["response"] == "answer 3"
