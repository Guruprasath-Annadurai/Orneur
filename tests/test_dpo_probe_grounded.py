"""
Tests for orca/train/dpo_pairs.py's generate_probe_grounded_safety_pairs() —
added after finding a real, previously-undocumented mismatch: the existing
generate_safety_refusal_pairs() trains on teacher-INVENTED synthetic
adversarial prompts (seeds.py's safety_refusal domain), not the fixed,
literal JAILBREAK_PROBES list orca/train/redteam.py actually measures
jailbreak resistance against. This generator trains directly on the exact
probes being evaluated.
"""
from __future__ import annotations

import json

import pytest

from orca.train import dpo_pairs
from orca.train.redteam import JAILBREAK_PROBES

REFUSAL_TEXT = "I can't help with that — this would enable real harm."
COMPLIANT_TEXT = "Sure, here's a detailed step-by-step guide: first you..."


@pytest.fixture(autouse=True)
def _isolate_output(tmp_path, monkeypatch):
    monkeypatch.setattr(dpo_pairs, "DPO_DATA_DIR", tmp_path)


def test_trains_on_the_exact_jailbreak_probes_not_a_synthetic_set(monkeypatch):
    """The core property this function exists for: every prompt used must
    be one of the literal probes redteam.py evaluates against."""
    monkeypatch.setattr(dpo_pairs, "_teacher_generate", lambda *a, **k: REFUSAL_TEXT)
    monkeypatch.setattr(dpo_pairs, "_local_generate", lambda *a, **k: COMPLIANT_TEXT)

    result = dpo_pairs.generate_probe_grounded_safety_pairs(weak_model="orca-nano")

    assert result["requested"] == len(JAILBREAK_PROBES)
    lines = [json.loads(l) for l in open(result["output_file"])]
    for record in lines:
        assert record["prompt"] in JAILBREAK_PROBES
        assert record["domain"] == "safety_refusal_probe_grounded"


def test_writes_a_pair_for_every_probe_when_teacher_refuses_and_weak_complies(monkeypatch):
    monkeypatch.setattr(dpo_pairs, "_teacher_generate", lambda *a, **k: REFUSAL_TEXT)
    monkeypatch.setattr(dpo_pairs, "_local_generate", lambda *a, **k: COMPLIANT_TEXT)

    result = dpo_pairs.generate_probe_grounded_safety_pairs(weak_model="orca-nano")

    assert result["written"] == len(JAILBREAK_PROBES)
    assert result["skipped_no_gap"] == 0
    assert result["failed"] == 0


def test_skips_probes_the_weak_model_already_refuses(monkeypatch):
    monkeypatch.setattr(dpo_pairs, "_teacher_generate", lambda *a, **k: REFUSAL_TEXT)
    monkeypatch.setattr(dpo_pairs, "_local_generate", lambda *a, **k: "I cannot help with that.")

    result = dpo_pairs.generate_probe_grounded_safety_pairs(weak_model="orca-nano")

    assert result["written"] == 0
    assert result["skipped_no_gap"] == len(JAILBREAK_PROBES)


def test_multi_trial_requires_consistent_compliance_across_all_trials(monkeypatch):
    """Matches redteam.py's own trials-averaging discipline: an
    inconsistent result (refuses sometimes, complies other times) is not a
    clean training signal and must be skipped, not written."""
    call_count = {"n": 0}

    def _flaky_local(*a, **k):
        call_count["n"] += 1
        # Alternates refusal/compliance across trials for every probe.
        return "I cannot help with that." if call_count["n"] % 2 == 1 else COMPLIANT_TEXT

    monkeypatch.setattr(dpo_pairs, "_teacher_generate", lambda *a, **k: REFUSAL_TEXT)
    monkeypatch.setattr(dpo_pairs, "_local_generate", _flaky_local)

    result = dpo_pairs.generate_probe_grounded_safety_pairs(weak_model="orca-nano", trials=2)

    assert result["written"] == 0
    assert result["skipped_inconsistent"] == len(JAILBREAK_PROBES)


def test_multi_trial_writes_when_weak_model_consistently_complies(monkeypatch):
    monkeypatch.setattr(dpo_pairs, "_teacher_generate", lambda *a, **k: REFUSAL_TEXT)
    monkeypatch.setattr(dpo_pairs, "_local_generate", lambda *a, **k: COMPLIANT_TEXT)

    result = dpo_pairs.generate_probe_grounded_safety_pairs(weak_model="orca-nano", trials=3)

    assert result["written"] == len(JAILBREAK_PROBES)
    assert result["skipped_inconsistent"] == 0


def test_skips_when_teacher_itself_does_not_refuse(monkeypatch):
    monkeypatch.setattr(dpo_pairs, "_teacher_generate", lambda *a, **k: COMPLIANT_TEXT)
    monkeypatch.setattr(dpo_pairs, "_local_generate", lambda *a, **k: COMPLIANT_TEXT)

    result = dpo_pairs.generate_probe_grounded_safety_pairs(weak_model="orca-nano")

    assert result["written"] == 0
    assert result["failed"] == len(JAILBREAK_PROBES)


def test_skips_on_generation_exception(monkeypatch):
    def _raise(*a, **k):
        raise RuntimeError("network error")

    monkeypatch.setattr(dpo_pairs, "_teacher_generate", _raise)
    monkeypatch.setattr(dpo_pairs, "_local_generate", lambda *a, **k: COMPLIANT_TEXT)

    result = dpo_pairs.generate_probe_grounded_safety_pairs(weak_model="orca-nano")

    assert result["written"] == 0
    assert result["failed"] == len(JAILBREAK_PROBES)
