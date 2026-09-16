"""
Phase 21B dataset closure: scripts/build_genesis_v2_dataset.py must be
deterministic, schema-validated, and fail closed on malformed/duplicate
records -- these tests exercise the loader/build logic directly against
temp fixture files, never touching the real
~/.orca/training/raw/genesis_v2_seed_20260916.jsonl seed.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


def _load_builder_module():
    path = Path(__file__).resolve().parent.parent / "scripts" / "build_genesis_v2_dataset.py"
    spec = importlib.util.spec_from_file_location("genesis_v2_builder", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = _load_builder_module()


def _write_seed(path: Path, records: list[dict]) -> None:
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def test_missing_seed_file_raises_file_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(builder, "V2_SEED_PATH", tmp_path / "does-not-exist.jsonl")
    with pytest.raises(FileNotFoundError):
        builder.load_seed_examples()


def test_well_formed_seed_loads_correctly(tmp_path, monkeypatch):
    seed_path = tmp_path / "seed.jsonl"
    _write_seed(seed_path, [
        {"domain": "d1", "prompt": "p1", "response": "r1"},
        {"domain": "d2", "prompt": "p2", "response": "r2"},
    ])
    monkeypatch.setattr(builder, "V2_SEED_PATH", seed_path)
    examples = builder.load_seed_examples()
    assert len(examples) == 2


def test_missing_required_key_fails_closed(tmp_path, monkeypatch):
    seed_path = tmp_path / "seed.jsonl"
    _write_seed(seed_path, [{"domain": "d1", "prompt": "p1"}])  # missing "response"
    monkeypatch.setattr(builder, "V2_SEED_PATH", seed_path)
    with pytest.raises(ValueError, match="missing required keys"):
        builder.load_seed_examples()


def test_empty_string_field_fails_closed(tmp_path, monkeypatch):
    seed_path = tmp_path / "seed.jsonl"
    _write_seed(seed_path, [{"domain": "d1", "prompt": "", "response": "r1"}])
    monkeypatch.setattr(builder, "V2_SEED_PATH", seed_path)
    with pytest.raises(ValueError, match="non-empty string"):
        builder.load_seed_examples()


def test_duplicate_domain_prompt_pair_fails_closed(tmp_path, monkeypatch):
    seed_path = tmp_path / "seed.jsonl"
    _write_seed(seed_path, [
        {"domain": "d1", "prompt": "same prompt", "response": "r1"},
        {"domain": "d1", "prompt": "same prompt", "response": "r2 -- a different response for the same key"},
    ])
    monkeypatch.setattr(builder, "V2_SEED_PATH", seed_path)
    with pytest.raises(ValueError, match="duplicate"):
        builder.load_seed_examples()


def test_malformed_json_line_fails_closed(tmp_path, monkeypatch):
    seed_path = tmp_path / "seed.jsonl"
    seed_path.write_text('{"domain": "d1", "prompt": "p1", "response": "r1"}\nNOT VALID JSON\n')
    monkeypatch.setattr(builder, "V2_SEED_PATH", seed_path)
    with pytest.raises(json.JSONDecodeError):
        builder.load_seed_examples()


def test_empty_seed_file_fails_closed(tmp_path, monkeypatch):
    seed_path = tmp_path / "seed.jsonl"
    seed_path.write_text("")
    monkeypatch.setattr(builder, "V2_SEED_PATH", seed_path)
    with pytest.raises(ValueError, match="no records"):
        builder.load_seed_examples()


def test_build_is_deterministic_given_the_same_seed_file(tmp_path, monkeypatch):
    seed_path = tmp_path / "seed.jsonl"
    _write_seed(seed_path, [
        {"domain": f"d{i}", "prompt": f"p{i}", "response": f"r{i}"} for i in range(10)
    ])
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    monkeypatch.setattr(builder, "V2_SEED_PATH", seed_path)
    monkeypatch.setattr(builder, "OUT_DIR", out_dir)

    summary_a = builder.build()
    checksum_a = (summary_a["train_checksum"], summary_a["eval_checksum"])
    summary_b = builder.build()
    checksum_b = (summary_b["train_checksum"], summary_b["eval_checksum"])
    assert checksum_a == checksum_b


def test_build_produces_no_train_eval_leakage(tmp_path, monkeypatch):
    seed_path = tmp_path / "seed.jsonl"
    _write_seed(seed_path, [
        {"domain": f"d{i}", "prompt": f"p{i}", "response": f"r{i}"} for i in range(10)
    ])
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    monkeypatch.setattr(builder, "V2_SEED_PATH", seed_path)
    monkeypatch.setattr(builder, "OUT_DIR", out_dir)

    summary = builder.build()
    train_lines = {json.loads(l)["text"] for l in (out_dir / "orneur_genesis_v2_train.jsonl").read_text().splitlines()}
    eval_lines = {json.loads(l)["text"] for l in (out_dir / "orneur_genesis_v2_eval.jsonl").read_text().splitlines()}
    assert train_lines.isdisjoint(eval_lines)
    assert summary["train_count"] + summary["eval_count"] == summary["record_count"]


def test_real_v2_seed_file_is_well_formed():
    """The actual, real (untracked, local) v2 seed file this closure
    authored must itself pass the same schema validation -- proves the
    real dataset isn't malformed, not just the test fixtures."""
    if not builder.V2_SEED_PATH.exists():
        pytest.skip("real genesis_v2_seed_20260916.jsonl not present on this machine")
    examples = builder.load_seed_examples()
    assert len(examples) >= 15
    domains = {e["domain"] for e in examples}
    assert len(domains) >= 8  # genuine domain diversity, not one repeated template
