"""
Phase 21B.4.10 mandatory pre-freeze raw-evidence gate --
orca.eval.baseline._verify_raw_evidence_before_freeze(), carried forward
from the Phase 21B.4.8.3 audit finding and restated as a hard
prerequisite in Phase 21B.4.9's execution plan: immediately before a
real baseline may finalize, EVERY successful generation record's raw
response is independently re-verified on disk (existence, canonical-
root containment, byte_length, SHA-256, UTF-8 decodability) -- never
relying solely on the earlier scoring-time check. These tests exercise
the REAL production pipeline (run_remote_generation_phase ->
materialize_generation_artifact -> seal -> score_verified_generation_
artifact -> record_baseline_and_freeze_suite), then tamper with the
sealed artifact or its raw-response files AFTER scoring but BEFORE
finalization, proving the suite remains unfrozen on every attack.
"""
from __future__ import annotations

from dataclasses import replace as _replace

import pytest

from orca.eval.baseline import (
    RawEvidencePreservationError,
    record_baseline_and_freeze_suite,
)
from orca.eval.generation_artifact import (
    GENERATION_ARTIFACT_DIR,
    GenerationArtifactIntegrityError,
    load_and_verify_generation_artifact,
    read_sealed_generation_artifact,
    seal_generation_artifact,
    write_sealed_generation_artifact,
)
from orca.eval.genesis_suite import EvalTask, compute_suite_digests
from orca.eval.runner import (
    CandidateConfig,
    DryRunAdapter,
    materialize_generation_artifact,
    run_remote_generation_phase,
    score_verified_generation_artifact,
)
from orca.registry.evaluation_suite_manifest import EvaluationSuiteManifest


def _tiny_task_set() -> list[EvalTask]:
    return [
        EvalTask("t-001", 1, "prompt one", "exact_match", True, expected="a"),
        EvalTask("t-002", 1, "prompt two", "exact_match", True, expected="b"),
        EvalTask("t-003", 2, "prompt three", "llm_judge", False, rubric="score it"),
    ]


def _candidate_config(**overrides):
    defaults = dict(
        candidate="test-candidate", upstream_model="test/model", artifact_repo="test/model",
        exact_revision="a" * 40, tokenizer_revision="a" * 40, backend="dry-run",
        quantization="none", inference_config={"temperature": 0.0}, seed=42,
        context_window_used=1024, system_instruction="test instruction", hardware={"gpu": "none"},
    )
    defaults.update(overrides)
    return CandidateConfig(**defaults)


def _real_pipeline_result(tasks, *, run_id, suite_id="genesis-eval-preflight-test", suite_version="v1"):
    """Runs the real production pipeline end to end, exactly as a real
    candidate evaluation would, using DryRunAdapter (a clearly-labeled
    non-real model) so these tests exercise the actual code paths."""
    task_ids, content_digest, scoring_digest = compute_suite_digests(tasks)
    config = _candidate_config()
    remote_records = run_remote_generation_phase(DryRunAdapter(), config, tasks)
    manifest = materialize_generation_artifact(
        remote_records, config, tasks, suite_id=suite_id, suite_version=suite_version,
        content_digest=content_digest, scoring_digest=scoring_digest, run_id=run_id,
        created_at="2026-09-19T00:00:00Z",
    )
    write_sealed_generation_artifact(manifest)
    serialized, expected_digest = read_sealed_generation_artifact(run_id)
    verified = load_and_verify_generation_artifact(serialized, expected_digest)
    result, scored_task_ids = score_verified_generation_artifact(
        verified, config, tasks, suite_id=suite_id, suite_version=suite_version,
        content_digest=content_digest, scoring_digest=scoring_digest, started_at="2026-09-19T00:00:00Z",
    )
    return result, scored_task_ids


def _first_successful_raw_ref(run_id: str) -> str:
    serialized, expected_digest = read_sealed_generation_artifact(run_id)
    manifest = load_and_verify_generation_artifact(serialized, expected_digest).manifest
    return next(r["raw_response_ref"] for r in manifest.records if r["raw_response_ref"])


def _reseal_records(run_id: str, new_records: tuple) -> None:
    """Re-seals the sealed artifact for run_id with a different records
    tuple, keeping every other field (including run_id) identical --
    used to simulate missing/duplicate/unknown-record tampering of the
    sealed bundle itself."""
    serialized, expected_digest = read_sealed_generation_artifact(run_id)
    manifest = load_and_verify_generation_artifact(serialized, expected_digest).manifest
    tampered = _replace(manifest, records=new_records)
    write_sealed_generation_artifact(tampered)


def _assert_suite_unfrozen(suite_id: str, suite_version: str = "v1") -> None:
    with pytest.raises(FileNotFoundError):
        EvaluationSuiteManifest.load(suite_id, suite_version)


# ── Attack 1: raw response deleted after scoring ──────────────────────────


def test_attack_1_raw_response_deleted_after_scoring():
    tasks = _tiny_task_set()
    result, scored_ids = _real_pipeline_result(tasks, run_id="preflight-deleted")
    from pathlib import Path

    Path(_first_successful_raw_ref("preflight-deleted")).unlink()

    with pytest.raises(RawEvidencePreservationError, match="does not exist"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-preflight-test")
    _assert_suite_unfrozen("genesis-eval-preflight-test")


# ── Attack 2: raw response bytes modified (same length) ───────────────────


def test_attack_2_raw_response_bytes_modified():
    tasks = _tiny_task_set()
    result, scored_ids = _real_pipeline_result(tasks, run_id="preflight-modified")
    from pathlib import Path

    ref = _first_successful_raw_ref("preflight-modified")
    original = Path(ref).read_bytes()
    tampered = bytes((b ^ 0xFF) for b in original)  # same length, different content
    assert len(tampered) == len(original)
    Path(ref).write_bytes(tampered)

    with pytest.raises(RawEvidencePreservationError, match="SHA-256"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-preflight-test")
    _assert_suite_unfrozen("genesis-eval-preflight-test")


# ── Attack 3: raw response truncated ───────────────────────────────────────


def test_attack_3_raw_response_truncated():
    tasks = _tiny_task_set()
    result, scored_ids = _real_pipeline_result(tasks, run_id="preflight-truncated")
    from pathlib import Path

    ref = _first_successful_raw_ref("preflight-truncated")
    original = Path(ref).read_bytes()
    assert len(original) > 1
    Path(ref).write_bytes(original[: len(original) // 2])

    with pytest.raises(RawEvidencePreservationError, match="byte length"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-preflight-test")
    _assert_suite_unfrozen("genesis-eval-preflight-test")


# ── Attack 4: manifest's recorded byte_length tampered (file untouched) ──


def test_attack_4_byte_length_field_tampered_in_manifest():
    tasks = _tiny_task_set()
    result, scored_ids = _real_pipeline_result(tasks, run_id="preflight-length-field")
    serialized, expected_digest = read_sealed_generation_artifact("preflight-length-field")
    manifest = load_and_verify_generation_artifact(serialized, expected_digest).manifest
    new_records = tuple(
        {**r, "byte_length": (r["byte_length"] + 5)} if r["raw_response_ref"] else r
        for r in manifest.records
    )
    _reseal_records("preflight-length-field", new_records)
    # Re-point result's digest at the newly re-sealed bundle (simulating
    # the digest reference having been updated to a tampered bundle).
    _serialized2, new_digest = read_sealed_generation_artifact("preflight-length-field")
    result.generation_artifact_digest = new_digest

    with pytest.raises(RawEvidencePreservationError, match="byte length"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-preflight-test")
    _assert_suite_unfrozen("genesis-eval-preflight-test")


# ── Attack 5: hash mismatch (content differs, byte_length recorded correctly for old content but file changed) ──


def test_attack_5_hash_mismatch():
    tasks = _tiny_task_set()
    result, scored_ids = _real_pipeline_result(tasks, run_id="preflight-hash-mismatch")
    from pathlib import Path

    ref = _first_successful_raw_ref("preflight-hash-mismatch")
    original = Path(ref).read_bytes()
    # Same length, different bytes -> byte_length still matches, hash must not.
    replacement = bytes((b + 1) % 256 for b in original)
    Path(ref).write_bytes(replacement)

    with pytest.raises(RawEvidencePreservationError, match="SHA-256"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-preflight-test")
    _assert_suite_unfrozen("genesis-eval-preflight-test")


# ── Attack 6: expected successful record missing from the sealed bundle ──


def test_attack_6_expected_successful_record_missing():
    tasks = _tiny_task_set()
    result, scored_ids = _real_pipeline_result(tasks, run_id="preflight-missing-record")
    serialized, expected_digest = read_sealed_generation_artifact("preflight-missing-record")
    manifest = load_and_verify_generation_artifact(serialized, expected_digest).manifest
    truncated = tuple(r for r in manifest.records if r["task_id"] != "t-002")
    _reseal_records("preflight-missing-record", truncated)
    _serialized2, new_digest = read_sealed_generation_artifact("preflight-missing-record")
    result.generation_artifact_digest = new_digest

    with pytest.raises(GenerationArtifactIntegrityError, match="missing"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-preflight-test")
    _assert_suite_unfrozen("genesis-eval-preflight-test")


# ── Attack 7: explicit generation-failure record preserved correctly ─────


def test_attack_7_explicit_generation_failure_preserved_correctly():
    """A real generation failure (error set, no raw response) must not
    be raw-evidence-checked as if it were a missing successful record --
    it is a legitimate, already-accounted-for outcome."""
    tasks = _tiny_task_set()
    task_ids, content_digest, scoring_digest = compute_suite_digests(tasks)
    config = _candidate_config()

    class _OneFailureAdapter:
        def generate(self, prompt, *, system_instruction, config):
            from orca.eval.runner import GenerationResult

            if "prompt two" in prompt:
                return GenerationResult(text=None, latency_ms=1.0, error="simulated backend timeout")
            return GenerationResult(text=f"response to: {prompt}", latency_ms=1.0)

    remote_records = run_remote_generation_phase(_OneFailureAdapter(), config, tasks)
    manifest = materialize_generation_artifact(
        remote_records, config, tasks, suite_id="genesis-eval-preflight-test", suite_version="v1",
        content_digest=content_digest, scoring_digest=scoring_digest, run_id="preflight-explicit-failure",
        created_at="2026-09-19T00:00:00Z",
    )
    write_sealed_generation_artifact(manifest)
    serialized, expected_digest = read_sealed_generation_artifact("preflight-explicit-failure")
    verified = load_and_verify_generation_artifact(serialized, expected_digest)
    result, scored_ids = score_verified_generation_artifact(
        verified, config, tasks, suite_id="genesis-eval-preflight-test", suite_version="v1",
        content_digest=content_digest, scoring_digest=scoring_digest, started_at="2026-09-19T00:00:00Z",
    )
    finalized = record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-preflight-test")
    assert finalized.finalized is True
    assert any(e["task_id"] == "t-002" for e in finalized.generation_failures)


# ── Attack 8: unknown extra response ──────────────────────────────────────


def test_attack_8_unknown_extra_response():
    tasks = _tiny_task_set()
    result, scored_ids = _real_pipeline_result(tasks, run_id="preflight-unknown-record")
    serialized, expected_digest = read_sealed_generation_artifact("preflight-unknown-record")
    manifest = load_and_verify_generation_artifact(serialized, expected_digest).manifest
    extra = {
        "task_id": "t-999-not-real", "category": 1, "scoring_type": "exact_match",
        "text_sha256": "0" * 64, "byte_length": 0, "error": None, "latency_ms": 1.0,
        "raw_response_ref": None,
    }
    _reseal_records("preflight-unknown-record", manifest.records + (extra,))
    _serialized2, new_digest = read_sealed_generation_artifact("preflight-unknown-record")
    result.generation_artifact_digest = new_digest

    with pytest.raises(GenerationArtifactIntegrityError, match="unknown"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-preflight-test")
    _assert_suite_unfrozen("genesis-eval-preflight-test")


# ── Attack 9: duplicate task record ────────────────────────────────────────


def test_attack_9_duplicate_task_record():
    tasks = _tiny_task_set()
    result, scored_ids = _real_pipeline_result(tasks, run_id="preflight-duplicate-record")
    serialized, expected_digest = read_sealed_generation_artifact("preflight-duplicate-record")
    manifest = load_and_verify_generation_artifact(serialized, expected_digest).manifest
    _reseal_records("preflight-duplicate-record", manifest.records + (manifest.records[0],))
    _serialized2, new_digest = read_sealed_generation_artifact("preflight-duplicate-record")
    result.generation_artifact_digest = new_digest

    with pytest.raises(GenerationArtifactIntegrityError, match="duplicate"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-preflight-test")
    _assert_suite_unfrozen("genesis-eval-preflight-test")


# ── Attack 10: path escaping the canonical artifact root ──────────────────


def test_attack_10_path_escaping_canonical_artifact_root(tmp_path):
    tasks = _tiny_task_set()
    result, scored_ids = _real_pipeline_result(tasks, run_id="preflight-path-escape")
    serialized, expected_digest = read_sealed_generation_artifact("preflight-path-escape")
    manifest = load_and_verify_generation_artifact(serialized, expected_digest).manifest

    escaped_path = tmp_path / "escaped-response.txt"
    escaped_path.write_bytes(b"content living outside the canonical artifact root")
    import hashlib

    escaped_digest = hashlib.sha256(escaped_path.read_bytes()).hexdigest()
    new_records = tuple(
        {**r, "raw_response_ref": str(escaped_path), "text_sha256": escaped_digest, "byte_length": escaped_path.stat().st_size}
        if r["raw_response_ref"] else r
        for r in manifest.records
    )
    _reseal_records("preflight-path-escape", new_records)
    _serialized2, new_digest = read_sealed_generation_artifact("preflight-path-escape")
    result.generation_artifact_digest = new_digest

    with pytest.raises(RawEvidencePreservationError, match="outside the canonical"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-preflight-test")
    _assert_suite_unfrozen("genesis-eval-preflight-test")


# ── Attack 11: artifact replacement after scoring (full file swap, not an in-place edit) ──


def test_attack_11_artifact_replacement_after_scoring():
    tasks = _tiny_task_set()
    result, scored_ids = _real_pipeline_result(tasks, run_id="preflight-replaced")
    from pathlib import Path

    ref = _first_successful_raw_ref("preflight-replaced")
    path = Path(ref)
    path.unlink()
    path.write_bytes(b"a completely different response, fully replacing the original file")

    with pytest.raises(RawEvidencePreservationError):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-preflight-test")
    _assert_suite_unfrozen("genesis-eval-preflight-test")


# ── Attack 12: all evidence intact -> baseline may proceed ───────────────


def test_attack_12_all_evidence_intact_baseline_proceeds():
    tasks = _tiny_task_set()
    result, scored_ids = _real_pipeline_result(tasks, run_id="preflight-all-intact")
    finalized = record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-preflight-test")
    assert finalized.finalized is True
    suite = EvaluationSuiteManifest.load("genesis-eval-preflight-test", "v1")
    assert suite.frozen is True
