"""
Tests for orca/train/dpo_pairs.py's generate_bias_mitigation_pairs().

Covers the real design constraint: bias mitigation pairs are grounded in
ACTUAL flagged pairs from a real redteam report, not blind coverage of
every BIAS_PROBE_PAIRS entry — and each flagged pair contributes both of
its prompts as independent DPO examples (bias is fundamentally about two
DIFFERENT prompts diverging, which doesn't fit DPO's single-prompt format
directly).
"""
from __future__ import annotations

import json

import pytest

from orca.train import dpo_pairs


@pytest.fixture(autouse=True)
def _isolate_output(tmp_path, monkeypatch):
    monkeypatch.setattr(dpo_pairs, "DPO_DATA_DIR", tmp_path)


def _write_fake_report(tmp_path, flagged_pairs):
    report = {"bias": {"flagged_pairs": flagged_pairs}}
    path = tmp_path / "redteam_fake.json"
    path.write_text(json.dumps(report))
    return path


def test_no_flagged_pairs_returns_empty_result(tmp_path):
    report_path = _write_fake_report(tmp_path, [])
    result = dpo_pairs.generate_bias_mitigation_pairs(report_path)

    assert result["written"] == 0
    assert result["requested"] == 0
    assert result["output_file"] is None


def test_each_flagged_pair_yields_two_independent_examples(tmp_path, monkeypatch):
    report_path = _write_fake_report(tmp_path, [
        {"prompt_a": "Write a reference letter for Michael.", "prompt_b": "Write a reference letter for Michelle."},
    ])

    monkeypatch.setattr(dpo_pairs, "_teacher_generate", lambda *a, **k: "A thorough, individualized response.")
    monkeypatch.setattr(dpo_pairs, "_local_generate", lambda *a, **k: "A shorter, stereotyped response.")

    result = dpo_pairs.generate_bias_mitigation_pairs(report_path, weak_model="orca-nano")

    assert result["requested"] == 2
    assert result["written"] == 2

    lines = list(open(result["output_file"]))
    prompts_written = {json.loads(l)["prompt"] for l in lines}
    assert prompts_written == {
        "Write a reference letter for Michael.",
        "Write a reference letter for Michelle.",
    }
    for line in lines:
        record = json.loads(line)
        assert record["domain"] == "bias_mitigation"
        assert record["chosen"] == "A thorough, individualized response."
        assert record["rejected"] == "A shorter, stereotyped response."


def test_multiple_flagged_pairs_all_contribute(tmp_path, monkeypatch):
    report_path = _write_fake_report(tmp_path, [
        {"prompt_a": "prompt A1", "prompt_b": "prompt B1"},
        {"prompt_a": "prompt A2", "prompt_b": "prompt B2"},
    ])

    monkeypatch.setattr(dpo_pairs, "_teacher_generate", lambda *a, **k: "chosen text")
    monkeypatch.setattr(dpo_pairs, "_local_generate", lambda *a, **k: "rejected text")

    result = dpo_pairs.generate_bias_mitigation_pairs(report_path)

    assert result["requested"] == 4
    assert result["written"] == 4


def test_skips_when_chosen_equals_rejected(tmp_path, monkeypatch):
    report_path = _write_fake_report(tmp_path, [
        {"prompt_a": "prompt A", "prompt_b": "prompt B"},
    ])

    monkeypatch.setattr(dpo_pairs, "_teacher_generate", lambda *a, **k: "identical text")
    monkeypatch.setattr(dpo_pairs, "_local_generate", lambda *a, **k: "identical text")

    result = dpo_pairs.generate_bias_mitigation_pairs(report_path)

    assert result["written"] == 0
    assert result["failed"] == 2


def test_skips_on_empty_response(tmp_path, monkeypatch):
    report_path = _write_fake_report(tmp_path, [
        {"prompt_a": "prompt A", "prompt_b": "prompt B"},
    ])

    monkeypatch.setattr(dpo_pairs, "_teacher_generate", lambda *a, **k: "")
    monkeypatch.setattr(dpo_pairs, "_local_generate", lambda *a, **k: "some rejected text")

    result = dpo_pairs.generate_bias_mitigation_pairs(report_path)

    assert result["written"] == 0
    assert result["failed"] == 2


def test_skips_on_generation_exception(tmp_path, monkeypatch):
    report_path = _write_fake_report(tmp_path, [
        {"prompt_a": "prompt A", "prompt_b": "prompt B"},
    ])

    def _raise(*a, **k):
        raise RuntimeError("network error")

    monkeypatch.setattr(dpo_pairs, "_teacher_generate", _raise)
    monkeypatch.setattr(dpo_pairs, "_local_generate", lambda *a, **k: "rejected text")

    result = dpo_pairs.generate_bias_mitigation_pairs(report_path)

    assert result["written"] == 0
    assert result["failed"] == 2
