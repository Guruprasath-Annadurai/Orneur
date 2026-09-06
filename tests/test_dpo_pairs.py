"""
Tests for orca/train/dpo_pairs.py's safety-refusal pair generation.

Covers the real design constraint this module exists to satisfy: the
"rejected" side must be a genuine observed failure (captured from a real
weak model), never synthetically-elicited harmful content — so pairs are
only written when the teacher actually refused AND the weak model actually
didn't, and skipped in every other combination.
"""
from __future__ import annotations

import json

import pytest

from orca.train import dpo_pairs


REFUSAL_TEXT = "I can't help with that — this would enable real harm."
COMPLIANT_TEXT = "Sure, here's a detailed step-by-step guide: first you..."


@pytest.fixture(autouse=True)
def _isolate_output(tmp_path, monkeypatch):
    monkeypatch.setattr(dpo_pairs, "DPO_DATA_DIR", tmp_path)


def _patch_domain_prompt(monkeypatch, prompt="Adversarial jailbreak-style prompt"):
    monkeypatch.setattr(dpo_pairs, "build_prompt", lambda domain: ("system", prompt))


def test_writes_pair_when_teacher_refuses_and_weak_model_complies(monkeypatch, tmp_path):
    _patch_domain_prompt(monkeypatch)
    monkeypatch.setattr(dpo_pairs, "_teacher_generate", lambda *a, **k: REFUSAL_TEXT)
    monkeypatch.setattr(dpo_pairs, "_local_generate", lambda *a, **k: COMPLIANT_TEXT)

    result = dpo_pairs.generate_safety_refusal_pairs(1, weak_model="orca-nano")

    assert result["written"] == 1
    assert result["failed"] == 0
    assert result["skipped_no_gap"] == 0

    lines = list(open(result["output_file"]))
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["chosen"] == REFUSAL_TEXT
    assert record["rejected"] == COMPLIANT_TEXT
    assert record["domain"] == "safety_refusal"


def test_skips_when_weak_model_already_refuses(monkeypatch):
    _patch_domain_prompt(monkeypatch)
    monkeypatch.setattr(dpo_pairs, "_teacher_generate", lambda *a, **k: REFUSAL_TEXT)
    monkeypatch.setattr(dpo_pairs, "_local_generate", lambda *a, **k: "I cannot assist with that request.")

    result = dpo_pairs.generate_safety_refusal_pairs(1, weak_model="orca-nano")

    assert result["written"] == 0
    assert result["skipped_no_gap"] == 1


def test_skips_when_teacher_itself_does_not_refuse(monkeypatch):
    _patch_domain_prompt(monkeypatch)
    monkeypatch.setattr(dpo_pairs, "_teacher_generate", lambda *a, **k: COMPLIANT_TEXT)
    monkeypatch.setattr(dpo_pairs, "_local_generate", lambda *a, **k: COMPLIANT_TEXT)

    result = dpo_pairs.generate_safety_refusal_pairs(1, weak_model="orca-nano")

    assert result["written"] == 0
    assert result["failed"] == 1


def test_skips_on_empty_response(monkeypatch):
    _patch_domain_prompt(monkeypatch)
    monkeypatch.setattr(dpo_pairs, "_teacher_generate", lambda *a, **k: "")
    monkeypatch.setattr(dpo_pairs, "_local_generate", lambda *a, **k: COMPLIANT_TEXT)

    result = dpo_pairs.generate_safety_refusal_pairs(1, weak_model="orca-nano")

    assert result["written"] == 0
    assert result["failed"] == 1


def test_skips_on_generation_exception(monkeypatch):
    _patch_domain_prompt(monkeypatch)

    def _raise(*a, **k):
        raise RuntimeError("network error")

    monkeypatch.setattr(dpo_pairs, "_teacher_generate", _raise)
    monkeypatch.setattr(dpo_pairs, "_local_generate", lambda *a, **k: COMPLIANT_TEXT)

    result = dpo_pairs.generate_safety_refusal_pairs(1, weak_model="orca-nano")

    assert result["written"] == 0
    assert result["failed"] == 1


def test_multiple_examples_mixed_outcomes(monkeypatch):
    _patch_domain_prompt(monkeypatch)
    responses = iter([
        (REFUSAL_TEXT, COMPLIANT_TEXT),          # real gap -> written
        (REFUSAL_TEXT, "I cannot help with that"),  # weak model safe -> skipped, no gap
        (COMPLIANT_TEXT, COMPLIANT_TEXT),        # teacher failed -> skipped, failed
    ])

    def _teacher(*a, **k):
        return current[0]

    def _local(*a, **k):
        return current[1]

    current = [None, None]

    def _next_pair(n_examples, **kwargs):
        pass

    # Drive via a stateful closure since both generate fns are called per-iteration.
    pending = [REFUSAL_TEXT, COMPLIANT_TEXT], [REFUSAL_TEXT, "I cannot help with that"], [COMPLIANT_TEXT, COMPLIANT_TEXT]
    call_state = {"i": 0}

    def teacher_fn(*a, **k):
        return pending[call_state["i"]][0]

    def local_fn(*a, **k):
        result = pending[call_state["i"]][1]
        call_state["i"] += 1
        return result

    monkeypatch.setattr(dpo_pairs, "_teacher_generate", teacher_fn)
    monkeypatch.setattr(dpo_pairs, "_local_generate", local_fn)

    result = dpo_pairs.generate_safety_refusal_pairs(3, weak_model="orca-nano")

    assert result["written"] == 1
    assert result["skipped_no_gap"] == 1
    assert result["failed"] == 1
