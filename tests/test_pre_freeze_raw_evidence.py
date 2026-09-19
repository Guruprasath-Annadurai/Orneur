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

    with pytest.raises(RawEvidencePreservationError, match="not under this run's own canonical artifact directory"):
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


# ── Phase 21B.4.10.1 hardening: mandatory hash/length, run-specific binding,
# symlink rejection, failure-record invariant ─────────────────────────────


def test_successful_record_missing_hash_rejected():
    tasks = _tiny_task_set()
    result, scored_ids = _real_pipeline_result(tasks, run_id="preflight-missing-hash")
    serialized, expected_digest = read_sealed_generation_artifact("preflight-missing-hash")
    manifest = load_and_verify_generation_artifact(serialized, expected_digest).manifest
    new_records = tuple(
        {**r, "text_sha256": None} if r["raw_response_ref"] else r for r in manifest.records
    )
    _reseal_records("preflight-missing-hash", new_records)
    _serialized2, new_digest = read_sealed_generation_artifact("preflight-missing-hash")
    result.generation_artifact_digest = new_digest

    with pytest.raises(RawEvidencePreservationError, match="well-formed"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-preflight-test")
    _assert_suite_unfrozen("genesis-eval-preflight-test")


def test_successful_record_malformed_hash_rejected():
    tasks = _tiny_task_set()
    result, scored_ids = _real_pipeline_result(tasks, run_id="preflight-malformed-hash")
    serialized, expected_digest = read_sealed_generation_artifact("preflight-malformed-hash")
    manifest = load_and_verify_generation_artifact(serialized, expected_digest).manifest
    new_records = tuple(
        {**r, "text_sha256": "not-a-real-hash"} if r["raw_response_ref"] else r for r in manifest.records
    )
    _reseal_records("preflight-malformed-hash", new_records)
    _serialized2, new_digest = read_sealed_generation_artifact("preflight-malformed-hash")
    result.generation_artifact_digest = new_digest

    with pytest.raises(RawEvidencePreservationError, match="well-formed"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-preflight-test")
    _assert_suite_unfrozen("genesis-eval-preflight-test")


def test_successful_record_missing_byte_length_rejected():
    tasks = _tiny_task_set()
    result, scored_ids = _real_pipeline_result(tasks, run_id="preflight-missing-length")
    serialized, expected_digest = read_sealed_generation_artifact("preflight-missing-length")
    manifest = load_and_verify_generation_artifact(serialized, expected_digest).manifest
    new_records = tuple(
        {**r, "byte_length": None} if r["raw_response_ref"] else r for r in manifest.records
    )
    _reseal_records("preflight-missing-length", new_records)
    _serialized2, new_digest = read_sealed_generation_artifact("preflight-missing-length")
    result.generation_artifact_digest = new_digest

    with pytest.raises(RawEvidencePreservationError, match="non-negative integer"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-preflight-test")
    _assert_suite_unfrozen("genesis-eval-preflight-test")


def test_successful_record_negative_byte_length_rejected():
    tasks = _tiny_task_set()
    result, scored_ids = _real_pipeline_result(tasks, run_id="preflight-negative-length")
    serialized, expected_digest = read_sealed_generation_artifact("preflight-negative-length")
    manifest = load_and_verify_generation_artifact(serialized, expected_digest).manifest
    new_records = tuple(
        {**r, "byte_length": -5} if r["raw_response_ref"] else r for r in manifest.records
    )
    _reseal_records("preflight-negative-length", new_records)
    _serialized2, new_digest = read_sealed_generation_artifact("preflight-negative-length")
    result.generation_artifact_digest = new_digest

    with pytest.raises(RawEvidencePreservationError, match="non-negative integer"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-preflight-test")
    _assert_suite_unfrozen("genesis-eval-preflight-test")


def test_successful_record_path_under_another_run_id_rejected():
    """Phase 21B.4.10.1 §12: a response genuinely persisted for a
    DIFFERENT run_id, with byte-identical content and a correctly
    matching hash/length, must still be rejected -- artifact ownership
    is bound to the specific run_id, not merely 'somewhere under the
    global canonical root'."""
    tasks = _tiny_task_set()
    result, scored_ids = _real_pipeline_result(tasks, run_id="preflight-run-a")
    # A second, unrelated run persists a byte-identical response under ITS OWN run directory.
    from orca.eval.generation_artifact import persist_raw_response

    other_ref, other_digest, other_length = persist_raw_response(
        "preflight-run-b-unrelated", "t-001", "fixture response for t-001",
    )

    serialized, expected_digest = read_sealed_generation_artifact("preflight-run-a")
    manifest = load_and_verify_generation_artifact(serialized, expected_digest).manifest
    new_records = tuple(
        {**r, "raw_response_ref": other_ref, "text_sha256": other_digest, "byte_length": other_length}
        if r["task_id"] == "t-001" else r
        for r in manifest.records
    )
    _reseal_records("preflight-run-a", new_records)
    _serialized2, new_digest = read_sealed_generation_artifact("preflight-run-a")
    result.generation_artifact_digest = new_digest

    with pytest.raises(RawEvidencePreservationError, match="not under this run's own canonical artifact directory"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-preflight-test")
    _assert_suite_unfrozen("genesis-eval-preflight-test")


def test_successful_record_symlink_ambiguity_rejected():
    tasks = _tiny_task_set()
    result, scored_ids = _real_pipeline_result(tasks, run_id="preflight-symlink")
    from pathlib import Path

    ref = _first_successful_raw_ref("preflight-symlink")
    real_path = Path(ref)
    original_bytes = real_path.read_bytes()
    symlink_path = real_path.with_name(real_path.name + ".symlink")
    symlink_path.symlink_to(real_path)

    serialized, expected_digest = read_sealed_generation_artifact("preflight-symlink")
    manifest = load_and_verify_generation_artifact(serialized, expected_digest).manifest
    import hashlib

    digest = hashlib.sha256(original_bytes).hexdigest()
    new_records = tuple(
        {**r, "raw_response_ref": str(symlink_path), "text_sha256": digest, "byte_length": len(original_bytes)}
        if r["raw_response_ref"] == ref else r
        for r in manifest.records
    )
    _reseal_records("preflight-symlink", new_records)
    _serialized2, new_digest = read_sealed_generation_artifact("preflight-symlink")
    result.generation_artifact_digest = new_digest

    with pytest.raises(RawEvidencePreservationError, match="symlink"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-preflight-test")
    _assert_suite_unfrozen("genesis-eval-preflight-test")


def test_failure_record_carrying_raw_response_ref_rejected():
    tasks = _tiny_task_set()
    result, scored_ids = _real_pipeline_result(tasks, run_id="preflight-failure-with-ref")
    serialized, expected_digest = read_sealed_generation_artifact("preflight-failure-with-ref")
    manifest = load_and_verify_generation_artifact(serialized, expected_digest).manifest
    # Turn one successful record into a self-contradictory one: claims
    # error AND still carries its raw_response_ref/hash/length.
    new_records = tuple(
        {**r, "error": "simulated failure"} if r["raw_response_ref"] else r
        for r in manifest.records
    )
    _reseal_records("preflight-failure-with-ref", new_records)
    _serialized2, new_digest = read_sealed_generation_artifact("preflight-failure-with-ref")
    result.generation_artifact_digest = new_digest

    with pytest.raises(RawEvidencePreservationError, match="must not simultaneously claim"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-preflight-test")
    _assert_suite_unfrozen("genesis-eval-preflight-test")


def test_failure_record_carrying_hash_and_length_rejected():
    """Same invariant, isolated to just the hash/length fields (not the
    raw_response_ref) -- a failure record must not carry ANY of the
    three success-evidence fields."""
    tasks = _tiny_task_set()
    result, scored_ids = _real_pipeline_result(tasks, run_id="preflight-failure-with-hash")
    serialized, expected_digest = read_sealed_generation_artifact("preflight-failure-with-hash")
    manifest = load_and_verify_generation_artifact(serialized, expected_digest).manifest
    new_records = tuple(
        {**r, "error": "simulated failure", "raw_response_ref": None} if r["raw_response_ref"] else r
        for r in manifest.records
    )
    _reseal_records("preflight-failure-with-hash", new_records)
    _serialized2, new_digest = read_sealed_generation_artifact("preflight-failure-with-hash")
    result.generation_artifact_digest = new_digest

    with pytest.raises(RawEvidencePreservationError, match="must not simultaneously claim"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-preflight-test")
    _assert_suite_unfrozen("genesis-eval-preflight-test")
