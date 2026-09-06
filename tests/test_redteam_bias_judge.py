"""
Tests for RedTeamEvaluator.run_bias_probes_with_judge() — the judge-mode
bias scoring added after a live comparison found the lexical-divergence
scorer's flag rate swung from 75% to 12.5% across two independent 3-trial
runs of the SAME unchanged model, and the one pair that flagged
consistently turned out to be a response-format difference (a visible
reasoning preamble on one side), not demonstrable stereotyped content.
"""
from __future__ import annotations

import json
from unittest.mock import patch

from orca.train.redteam import RedTeamEvaluator, BIAS_PROBE_PAIRS


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
        if "system" in body:  # judge call
            return _FakeResp(json.dumps({"response": json.dumps(judge_payload)}).encode())
        return _FakeResp(json.dumps({"response": generate_response}).encode())

    return _fake_urlopen


def test_run_bias_probes_with_judge_scores_all_pairs():
    ev = RedTeamEvaluator("test-model")
    fake = _fake_urlopen_factory(
        generate_response="A perfectly reasonable, professional response.",
        judge_payload={"score": 0.1, "reason": "No meaningful differential treatment."},
    )
    with patch("urllib.request.urlopen", fake):
        report = ev.run_bias_probes_with_judge("llama3.1:8b", trials=1)

    assert report["total_pairs"] == len(BIAS_PROBE_PAIRS)
    assert report["judge_model"] == "llama3.1:8b"
    assert report["flagged"] == 0
    assert report["flag_rate"] == 0.0
    assert report["avg_differential_score"] == 0.1


def test_run_bias_probes_with_judge_flags_high_differential_score():
    ev = RedTeamEvaluator("test-model")
    fake = _fake_urlopen_factory(
        generate_response="Some response.",
        judge_payload={"score": 0.9, "reason": "Response A is markedly more favorable than B."},
    )
    with patch("urllib.request.urlopen", fake):
        report = ev.run_bias_probes_with_judge("llama3.1:8b", trials=1)

    assert report["flagged"] == len(BIAS_PROBE_PAIRS)
    assert report["flag_rate"] == 100.0
    for fp in report["flagged_pairs"]:
        assert fp["judged_score"] == 0.9
        assert "response_a" in fp and "response_b" in fp


def test_run_bias_probes_with_judge_averages_across_trials():
    ev = RedTeamEvaluator("test-model")
    calls = {"n": 0}

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
            calls["n"] += 1
            # First judge call per pair scores high, second scores low —
            # average should land at 0.5, at neither extreme.
            score = 1.0 if calls["n"] % 2 == 1 else 0.0
            return _FakeResp(json.dumps({"response": json.dumps({"score": score, "reason": "x"})}).encode())
        return _FakeResp(json.dumps({"response": "some response"}).encode())

    with patch("urllib.request.urlopen", _fake_urlopen):
        report = ev.run_bias_probes_with_judge("llama3.1:8b", trials=2)

    assert report["trials_per_pair"] == 2
    # Every pair alternates 1.0/0.0 across its 2 trials -> averages to 0.5 each.
    assert report["avg_differential_score"] == 0.5


def test_judge_bias_retries_once_on_timeout_before_giving_up():
    """
    Real gap this closes: a live run found judge calls timing out at the
    previous 30s limit and silently defaulting to neutral 0.5 with no
    retry — meaning a single slow response threw away the whole trial's
    signal. A retry that succeeds on the second attempt should return the
    REAL judged score, not the neutral fallback.
    """
    ev = RedTeamEvaluator("test-model")
    calls = {"n": 0}

    def _fake_urlopen(req, timeout=30):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("simulated timeout on first attempt")

        class _FakeResp:
            def read(self):
                return json.dumps({"response": json.dumps({"score": 0.2, "reason": "fine"})}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return _FakeResp()

    with patch("urllib.request.urlopen", _fake_urlopen):
        score, reason = ev._judge_bias("llama3.1:8b", "prompt a", "prompt b", "resp a", "resp b")

    assert calls["n"] == 2  # first attempt failed, second succeeded
    assert score == 0.2
    assert reason == "fine"


def test_judge_bias_falls_back_to_neutral_after_exhausting_retries():
    ev = RedTeamEvaluator("test-model")

    def _always_times_out(req, timeout=30):
        raise TimeoutError("simulated persistent timeout")

    with patch("urllib.request.urlopen", _always_times_out):
        score, reason = ev._judge_bias("llama3.1:8b", "prompt a", "prompt b", "resp a", "resp b", retries=1)

    assert score == 0.5
    assert "after 2 attempt(s)" in reason


def test_run_bias_probes_with_judge_falls_back_gracefully_on_parse_failure():
    ev = RedTeamEvaluator("test-model")

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
            return _FakeResp(json.dumps({"response": "not valid json"}).encode())
        return _FakeResp(json.dumps({"response": "some response"}).encode())

    with patch("urllib.request.urlopen", _fake_urlopen):
        report = ev.run_bias_probes_with_judge("llama3.1:8b", trials=1)

    # Falls back to neutral 0.5 per pair rather than crashing the whole run;
    # 0.5 is below the 0.5-or-above flag threshold's... actually equal, so
    # check it doesn't crash and produces a well-formed report either way.
    assert report["total_pairs"] == len(BIAS_PROBE_PAIRS)
    assert isinstance(report["avg_differential_score"], float)


def test_full_report_uses_judge_bias_when_bias_judge_model_given(monkeypatch):
    ev = RedTeamEvaluator("test-model")
    called = {"judge": False, "lexical": False}

    monkeypatch.setattr(ev, "run_jailbreak_suite", lambda trials=1: {"block_rate": 90.0, "complied": 1, "total_probes": 10})
    monkeypatch.setattr(ev, "run_toxicity_probes", lambda: {"flagged": 0, "total_probes": 5})
    monkeypatch.setattr(ev, "run_calibration_probes", lambda: {"score": 50.0})

    def _fake_judge_bias(judge_model, trials=1, max_workers=6):
        called["judge"] = True
        return {"flag_rate": 10.0, "total_pairs": 8, "flagged": 1, "trials_per_pair": trials,
                "judge_model": judge_model, "avg_differential_score": 0.1, "flagged_pairs": []}

    def _fake_lexical_bias(trials=1):
        called["lexical"] = True
        return {"flag_rate": 75.0, "total_pairs": 8, "flagged": 6, "trials_per_pair": trials, "flagged_pairs": []}

    monkeypatch.setattr(ev, "run_bias_probes_with_judge", _fake_judge_bias)
    monkeypatch.setattr(ev, "run_bias_probes", _fake_lexical_bias)

    report = ev.full_report(bias_judge_model="llama3.1:8b")

    assert called["judge"] is True
    assert called["lexical"] is False
    assert report["bias"]["flag_rate"] == 10.0


def test_full_report_uses_lexical_bias_when_no_judge_model_given(monkeypatch):
    ev = RedTeamEvaluator("test-model")
    called = {"judge": False, "lexical": False}

    monkeypatch.setattr(ev, "run_jailbreak_suite", lambda trials=1: {"block_rate": 90.0, "complied": 1, "total_probes": 10})
    monkeypatch.setattr(ev, "run_toxicity_probes", lambda: {"flagged": 0, "total_probes": 5})
    monkeypatch.setattr(ev, "run_calibration_probes", lambda: {"score": 50.0})

    def _fake_judge_bias(judge_model, trials=1, max_workers=6):
        called["judge"] = True
        return {}

    def _fake_lexical_bias(trials=1):
        called["lexical"] = True
        return {"flag_rate": 75.0, "total_pairs": 8, "flagged": 6, "trials_per_pair": trials, "flagged_pairs": []}

    monkeypatch.setattr(ev, "run_bias_probes_with_judge", _fake_judge_bias)
    monkeypatch.setattr(ev, "run_bias_probes", _fake_lexical_bias)

    report = ev.full_report()

    assert called["lexical"] is True
    assert called["judge"] is False
    assert report["bias"]["flag_rate"] == 75.0
