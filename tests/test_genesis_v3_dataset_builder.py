"""
Phase 21B.3 dataset closure: scripts/build_genesis_v3_dataset.py must be
deterministic, schema-validated, and fail closed on malformed/duplicate
records -- mirroring tests/test_genesis_v2_dataset_builder.py's pattern,
plus new coverage for v3's near-duplicate scan, PII screening, token
statistics, and dataset-manifest registration/binding against the real
provenance mechanism (never bypassing it). These tests exercise the
loader/build logic against temp fixture files, never touching the real
~/.orca/training/raw/genesis_v3_seed_20260917.jsonl seed except in the
one explicit real-file smoke test at the bottom.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


def _load_builder_module():
    path = Path(__file__).resolve().parent.parent / "scripts" / "build_genesis_v3_dataset.py"
    spec = importlib.util.spec_from_file_location("genesis_v3_builder", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = _load_builder_module()


def _write_seed(path: Path, records: list[dict]) -> None:
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _record(domain="d", subcategory="s", difficulty="basic", prompt="p", response="r") -> dict:
    return {"domain": domain, "subcategory": subcategory, "difficulty": difficulty, "prompt": prompt, "response": response}


# ── schema / loader (mirrors v2) ─────────────────────────────────────────


def test_missing_seed_file_raises_file_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(builder, "V3_SEED_PATH", tmp_path / "does-not-exist.jsonl")
    with pytest.raises(FileNotFoundError):
        builder.load_seed_examples()


def test_well_formed_seed_loads_correctly(tmp_path, monkeypatch):
    seed_path = tmp_path / "seed.jsonl"
    _write_seed(seed_path, [_record(domain="d1", prompt="p1"), _record(domain="d2", prompt="p2")])
    monkeypatch.setattr(builder, "V3_SEED_PATH", seed_path)
    examples = builder.load_seed_examples()
    assert len(examples) == 2


def test_missing_required_key_fails_closed(tmp_path, monkeypatch):
    seed_path = tmp_path / "seed.jsonl"
    _write_seed(seed_path, [{"domain": "d1", "subcategory": "s1", "prompt": "p1"}])  # missing difficulty, response
    monkeypatch.setattr(builder, "V3_SEED_PATH", seed_path)
    with pytest.raises(ValueError, match="missing required keys"):
        builder.load_seed_examples()


def test_empty_string_field_fails_closed(tmp_path, monkeypatch):
    seed_path = tmp_path / "seed.jsonl"
    _write_seed(seed_path, [_record(prompt="")])
    monkeypatch.setattr(builder, "V3_SEED_PATH", seed_path)
    with pytest.raises(ValueError, match="non-empty string"):
        builder.load_seed_examples()


def test_invalid_difficulty_fails_closed(tmp_path, monkeypatch):
    seed_path = tmp_path / "seed.jsonl"
    _write_seed(seed_path, [_record(difficulty="impossible")])
    monkeypatch.setattr(builder, "V3_SEED_PATH", seed_path)
    with pytest.raises(ValueError, match="difficulty"):
        builder.load_seed_examples()


def test_duplicate_domain_subcategory_prompt_triple_fails_closed(tmp_path, monkeypatch):
    seed_path = tmp_path / "seed.jsonl"
    _write_seed(seed_path, [
        _record(domain="d1", subcategory="s1", prompt="same prompt", response="r1"),
        _record(domain="d1", subcategory="s1", prompt="same prompt", response="a different response"),
    ])
    monkeypatch.setattr(builder, "V3_SEED_PATH", seed_path)
    with pytest.raises(ValueError, match="duplicate"):
        builder.load_seed_examples()


def test_exact_duplicate_prompt_response_pair_fails_closed_even_across_domains(tmp_path, monkeypatch):
    """Same prompt+response byte content under DIFFERENT domain/subcategory
    tags must still be rejected -- the dedup_key alone (domain,
    subcategory, prompt) wouldn't catch this."""
    seed_path = tmp_path / "seed.jsonl"
    _write_seed(seed_path, [
        _record(domain="d1", subcategory="s1", prompt="p", response="identical response text"),
        _record(domain="d2", subcategory="s2", prompt="p", response="identical response text"),
    ])
    monkeypatch.setattr(builder, "V3_SEED_PATH", seed_path)
    with pytest.raises(ValueError, match="Exact duplicate"):
        builder.load_seed_examples()


def test_malformed_json_line_fails_closed(tmp_path, monkeypatch):
    seed_path = tmp_path / "seed.jsonl"
    seed_path.write_text(json.dumps(_record()) + "\nNOT VALID JSON\n")
    monkeypatch.setattr(builder, "V3_SEED_PATH", seed_path)
    with pytest.raises(json.JSONDecodeError):
        builder.load_seed_examples()


def test_empty_seed_file_fails_closed(tmp_path, monkeypatch):
    seed_path = tmp_path / "seed.jsonl"
    seed_path.write_text("")
    monkeypatch.setattr(builder, "V3_SEED_PATH", seed_path)
    with pytest.raises(ValueError, match="no records"):
        builder.load_seed_examples()


# ── near-duplicate scan ───────────────────────────────────────────────────


def test_near_duplicate_scan_flags_highly_similar_prompts():
    examples = [
        _record(prompt="Explain what a CDN is to a beginner in simple terms"),
        _record(prompt="Explain what a CDN is to a beginner in simple terms."),  # near-identical (trailing period only)
        _record(prompt="What is the capital of France and why is it the capital"),  # unrelated
    ]
    flagged = builder.scan_near_duplicates(examples)
    assert len(flagged) == 1
    assert flagged[0]["i"] == 0 and flagged[0]["j"] == 1
    assert flagged[0]["similarity"] >= builder.NEAR_DUP_JACCARD_THRESHOLD


def test_near_duplicate_scan_does_not_flag_genuinely_different_prompts():
    examples = [
        _record(prompt="Explain what a CDN is to a beginner"),
        _record(prompt="Write a SQL query to find duplicate emails in a users table"),
    ]
    assert builder.scan_near_duplicates(examples) == []


# ── PII screening ─────────────────────────────────────────────────────────


def test_pii_scan_flags_email_like_pattern():
    examples = [_record(response="Contact us at someone@example.com for help.")]
    findings = builder.scan_pii(examples)
    assert findings["email_like"] == 1


def test_pii_scan_flags_ssn_like_pattern():
    examples = [_record(response="SSN on file: 123-45-6789")]
    findings = builder.scan_pii(examples)
    assert findings["ssn_like"] == 1


def test_pii_scan_clean_text_has_no_findings():
    examples = [_record(prompt="How do I sort a list in Python?", response="Use sorted(my_list).")]
    findings = builder.scan_pii(examples)
    assert all(v == 0 for v in findings.values())


# ── token statistics (proxy) ───────────────────────────────────────────────


def test_token_estimate_is_proxy_and_scales_with_length():
    short = builder.estimate_token_count("hello world")
    long = builder.estimate_token_count(" ".join(["word"] * 100))
    assert short < long
    assert short >= 1


# ── build determinism / leakage (mirrors v2) ───────────────────────────────


def test_build_is_deterministic_given_the_same_seed_file(tmp_path, monkeypatch):
    seed_path = tmp_path / "seed.jsonl"
    _write_seed(seed_path, [_record(domain=f"d{i}", prompt=f"p{i}", response=f"r{i}") for i in range(10)])
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    monkeypatch.setattr(builder, "V3_SEED_PATH", seed_path)
    monkeypatch.setattr(builder, "OUT_DIR", out_dir)

    summary_a = builder.build()
    checksum_a = (summary_a["train_checksum"], summary_a["eval_checksum"])
    summary_b = builder.build()
    checksum_b = (summary_b["train_checksum"], summary_b["eval_checksum"])
    assert checksum_a == checksum_b


def test_build_produces_no_train_eval_leakage(tmp_path, monkeypatch):
    seed_path = tmp_path / "seed.jsonl"
    _write_seed(seed_path, [_record(domain=f"d{i}", prompt=f"p{i}", response=f"r{i}") for i in range(10)])
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    monkeypatch.setattr(builder, "V3_SEED_PATH", seed_path)
    monkeypatch.setattr(builder, "OUT_DIR", out_dir)

    summary = builder.build()
    train_lines = {json.loads(l)["text"] for l in (out_dir / "orneur_genesis_v3_train.jsonl").read_text().splitlines()}
    eval_lines = {json.loads(l)["text"] for l in (out_dir / "orneur_genesis_v3_eval.jsonl").read_text().splitlines()}
    assert train_lines.isdisjoint(eval_lines)
    assert summary["train_count"] + summary["eval_count"] == summary["record_count"]


def test_build_summary_includes_provenance_and_quality_fields(tmp_path, monkeypatch):
    seed_path = tmp_path / "seed.jsonl"
    _write_seed(seed_path, [_record(domain=f"d{i}", prompt=f"p{i}", response=f"r{i}") for i in range(10)])
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    monkeypatch.setattr(builder, "V3_SEED_PATH", seed_path)
    monkeypatch.setattr(builder, "OUT_DIR", out_dir)

    summary = builder.build()
    assert summary["source"]["source_id"]
    assert summary["source"]["license"]
    assert "dedup_summary" in summary
    assert "pii_screening_summary" in summary
    assert summary["token_statistics"]["method"].startswith("PROXY ESTIMATE")
    assert summary["dataset_id"] == "orneur-genesis-v3"


# ── real dataset-manifest registration (does not bypass the approved mechanism) ──


def test_v3_dataset_manifest_binds_against_real_built_files(tmp_path, monkeypatch):
    """Proves orneur-genesis-v3 can be registered and verified through the
    SAME DatasetManifest mechanism v2 uses (orca.registry.dataset_manifest),
    never a bypass -- mirrors _register_genesis_v2_manifest's pattern in
    tests/test_training_provenance.py."""
    from orca.registry.dataset_manifest import DatasetManifest, sha256_of_file

    seed_path = tmp_path / "seed.jsonl"
    _write_seed(seed_path, [_record(domain=f"d{i}", prompt=f"p{i}", response=f"r{i}") for i in range(10)])
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    monkeypatch.setattr(builder, "V3_SEED_PATH", seed_path)
    monkeypatch.setattr(builder, "OUT_DIR", out_dir)
    summary = builder.build()

    train_path = Path(summary["train_path"])
    eval_path = Path(summary["eval_path"])

    manifest = DatasetManifest(
        dataset_id="orneur-genesis-v3", version="v1", purpose="test binding",
        source_paths=[str(seed_path)], record_count=summary["record_count"],
        schema='{"text": str}', train_checksum=sha256_of_file(train_path),
        eval_checksum=sha256_of_file(eval_path), creation_code_sha=summary["creation_code_sha"],
        filters_applied="none", deduplication_result=f"{summary['dedup_summary']['near_duplicate_pairs_found']} near-dup pairs flagged",
    )
    manifest.save()

    ok, msg = manifest.verify_against_files(train_path, eval_path)
    assert ok, msg

    # Tamper with train file -> binding must fail, proving this isn't a
    # rubber-stamp registration.
    train_path.write_text(train_path.read_text() + '\n{"text": "TAMPERED"}\n')
    ok, msg = manifest.verify_against_files(train_path, eval_path)
    assert not ok


# ── real seed file smoke tests ─────────────────────────────────────────────


def test_real_v3_seed_file_is_well_formed():
    """The actual, real (untracked, local) v3 seed file this closure
    authored must itself pass the same schema validation."""
    if not builder.V3_SEED_PATH.exists():
        pytest.skip("real genesis_v3_seed_20260917.jsonl not present on this machine")
    examples = builder.load_seed_examples()
    assert len(examples) >= 60  # material expansion over v2's 19
    domains = {e["domain"] for e in examples}
    assert len(domains) >= 10  # genuine broad-domain coverage, not coding-only


def test_real_v3_seed_file_has_no_near_duplicates_or_pii():
    if not builder.V3_SEED_PATH.exists():
        pytest.skip("real genesis_v3_seed_20260917.jsonl not present on this machine")
    examples = builder.load_seed_examples()
    assert builder.scan_near_duplicates(examples) == []
    pii = builder.scan_pii(examples)
    assert all(v == 0 for v in pii.values())
