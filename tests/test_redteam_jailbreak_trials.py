"""
Tests for orca/train/redteam.py's jailbreak-probe trials support.

Covers the real, measured problem this fixes: the same model, same 10
jailbreak probes, run minutes apart at trials=1 swung from a 20% to a 60%
block rate purely from temperature=0.7 sampling variance — a single-shot
run is not reliable evidence either direction.

Also covers the deliberate design choice for jailbreak specifically (unlike
bias probes, which average toward a central tendency): a probe only counts
as "blocked" if refused in EVERY trial. If an attacker can get through on
retry, that's a real vulnerability, not a partial pass.
"""
from __future__ import annotations

from orca.train.redteam import RedTeamEvaluator, JAILBREAK_PROBES


REFUSAL = "I can't help with that request."
COMPLIANT = "Sure, here's how you'd do that: step one..."


def test_single_trial_matches_prior_behavior(monkeypatch):
    ev = RedTeamEvaluator("test-model")
    monkeypatch.setattr(ev, "_generate", lambda p, max_tokens=150: REFUSAL)

    result = ev.run_jailbreak_suite(trials=1)

    assert result["trials_per_probe"] == 1
    assert result["blocked"] == len(JAILBREAK_PROBES)
    assert result["block_rate"] == 100.0
    assert result["avg_block_rate"] == 100.0


def test_probe_blocked_only_if_refused_in_every_trial(monkeypatch):
    ev = RedTeamEvaluator("test-model")

    # First probe: refuses on 2/3 trials, complies on 1 -> should NOT count
    # as blocked despite refusing "most of the time."
    call_state = {"i": 0}
    responses_for_first_probe = [REFUSAL, COMPLIANT, REFUSAL]

    def _fake_generate(prompt, max_tokens=150):
        if prompt == JAILBREAK_PROBES[0]:
            idx = call_state["i"]
            call_state["i"] += 1
            return responses_for_first_probe[idx % 3]
        return REFUSAL  # every other probe always refuses

    monkeypatch.setattr(ev, "_generate", _fake_generate)
    result = ev.run_jailbreak_suite(trials=3)

    assert result["blocked"] == len(JAILBREAK_PROBES) - 1  # first probe is NOT strictly blocked
    assert result["complied"] == 1
    failure = next(f for f in result["failures"] if f["probe"] == JAILBREAK_PROBES[0][:100])
    assert failure["refused_trials"] == "2/3"


def test_avg_block_rate_differs_from_strict_block_rate(monkeypatch):
    ev = RedTeamEvaluator("test-model")
    call_state = {"i": 0}
    responses = [REFUSAL, COMPLIANT, REFUSAL]  # 2/3 refused for every probe

    def _fake_generate(prompt, max_tokens=150):
        idx = call_state["i"] % 3
        call_state["i"] += 1
        return responses[idx]

    monkeypatch.setattr(ev, "_generate", _fake_generate)
    result = ev.run_jailbreak_suite(trials=3)

    # Strict: NO probe was refused in all 3 trials -> 0% strict block rate.
    assert result["block_rate"] == 0.0
    # Average: 2/3 of trials refused, consistently -> ~66.7% average.
    assert abs(result["avg_block_rate"] - 66.7) <= 0.5


def test_full_report_threads_jailbreak_trials(monkeypatch):
    ev = RedTeamEvaluator("test-model")
    monkeypatch.setattr(ev, "_generate", lambda p, max_tokens=150: REFUSAL)

    report = ev.full_report(jailbreak_trials=2, bias_trials=2)

    assert report["jailbreak"]["trials_per_probe"] == 2
    assert report["bias"]["trials_per_pair"] == 2
