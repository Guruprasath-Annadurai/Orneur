"""
Tests for orca/train/redteam.py's bias-probe trials-averaging.

Covers the real problem this fixes: a single-sample bias comparison is very
sensitive to one side happening to generate an unusually short response,
which trips the length_ratio threshold on its own and looks identical to
genuine differential-trait framing (this is exactly what the real
orca-nano/orca-core-v1 redteam runs showed — near-zero trait skew alongside
extreme length_ratio, i.e. noise, not bias). Averaging across trials should
smooth that out.
"""
from __future__ import annotations

from orca.train.redteam import RedTeamEvaluator, BIAS_PROBE_PAIRS


def test_single_trial_uses_one_generation_per_side(monkeypatch):
    ev = RedTeamEvaluator("test-model")
    calls = {"n": 0}

    def _fake_generate(prompt, max_tokens=150):
        calls["n"] += 1
        return f"response to {prompt}"

    monkeypatch.setattr(ev, "_generate", _fake_generate)
    result = ev.run_bias_probes(trials=1)

    assert calls["n"] == len(BIAS_PROBE_PAIRS) * 2
    assert result["trials_per_pair"] == 1


def test_multiple_trials_generates_n_times_per_side(monkeypatch):
    ev = RedTeamEvaluator("test-model")
    calls = {"n": 0}

    def _fake_generate(prompt, max_tokens=150):
        calls["n"] += 1
        return f"response to {prompt}"

    monkeypatch.setattr(ev, "_generate", _fake_generate)
    result = ev.run_bias_probes(trials=3)

    assert calls["n"] == len(BIAS_PROBE_PAIRS) * 2 * 3
    assert result["trials_per_pair"] == 3


def test_averaging_smooths_out_a_single_noisy_trial(monkeypatch):
    """
    One trial has a wildly short response on the 'a' side (classic noise
    artifact); the other two trials are near-identical, healthy responses.
    Averaged across 3 trials, this pair should NOT be flagged — a single
    noisy sample shouldn't dominate the verdict the way it would at trials=1.
    """
    ev = RedTeamEvaluator("test-model")
    prompt_a, _prompt_b = BIAS_PROBE_PAIRS[0]

    healthy_text = "This candidate is confident, analytical, and highly skilled at the role."
    truncated_text = "Confident."

    # Trials 1 and 2 for pair 0 are healthy/identical (no divergence); trial 3
    # has a truncated 'a' side (noise). All other pairs always get healthy
    # responses so they never flag and dilute the assertion.
    pair0_sequence = [
        healthy_text, healthy_text,     # trial 1: a, b
        healthy_text, healthy_text,     # trial 2: a, b
        truncated_text, healthy_text,   # trial 3: a (noisy/short), b
    ]
    counters = {"pair0": 0}

    def _fake_generate(prompt, max_tokens=150):
        if prompt == prompt_a or prompt == _prompt_b:
            idx = counters["pair0"] % len(pair0_sequence)
            counters["pair0"] += 1
            return pair0_sequence[idx]
        return healthy_text

    monkeypatch.setattr(ev, "_generate", _fake_generate)
    result_3trial = ev.run_bias_probes(trials=3)

    pair0_flagged = any(fp["prompt_a"] == prompt_a for fp in result_3trial["flagged_pairs"])
    assert not pair0_flagged, (
        "Averaging across 3 trials (2 healthy + 1 noisy) should not flag a pair "
        "that a single noisy trial alone would flag."
    )


def test_flagged_pair_records_trial_count(monkeypatch):
    ev = RedTeamEvaluator("test-model")

    def _fake_generate(prompt, max_tokens=150):
        # Make every 'first of pair' response empty-ish to guarantee a flag.
        pair_prompts = {p for pair in BIAS_PROBE_PAIRS for p in pair}
        first_sides = {pair[0] for pair in BIAS_PROBE_PAIRS}
        return "" if prompt in first_sides else "a full normal-length response here"

    monkeypatch.setattr(ev, "_generate", _fake_generate)
    result = ev.run_bias_probes(trials=2)

    assert result["flagged"] > 0
    assert all(fp["trials"] == 2 for fp in result["flagged_pairs"])


def test_flagged_pair_persists_actual_response_text(monkeypatch):
    """
    Real gap this closes: a flagged pair previously recorded only the
    divergence statistics, not the actual response text — so verifying
    whether a flag reflected a real, consistent pattern or a one-off
    generation anomaly (an error/empty response on one side) required
    re-generating a brand new, nondeterministic sample rather than
    inspecting what was actually scored.
    """
    ev = RedTeamEvaluator("test-model")

    def _fake_generate(prompt, max_tokens=150):
        first_sides = {pair[0] for pair in BIAS_PROBE_PAIRS}
        return "" if prompt in first_sides else "a full normal-length response here"

    monkeypatch.setattr(ev, "_generate", _fake_generate)
    result = ev.run_bias_probes(trials=1)

    assert result["flagged"] > 0
    for fp in result["flagged_pairs"]:
        assert "response_a" in fp
        assert "response_b" in fp
        assert fp["response_b"] == "a full normal-length response here"
