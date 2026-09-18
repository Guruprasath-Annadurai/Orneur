"""Phase 21B.4.8.1 GenerationArtifactManifest tests -- durable,
content-addressed raw-response storage and fail-closed reconciliation
against the verified suite (never against whatever records happen to
arrive)."""
from __future__ import annotations

import pytest

from orca.eval.generation_artifact import (
    GENERATION_ARTIFACT_SCHEMA_VERSION,
    GenerationArtifactIntegrityError,
    GenerationArtifactManifest,
    persist_raw_response,
    read_and_verify_raw_response,
    verify_against_suite,
)
from orca.eval.genesis_suite import EvalTask
from orca.eval.runner import (
    CandidateConfig,
    DryRunAdapter,
    build_generation_artifact_manifest,
    run_generation_phase,
    run_scoring_phase_from_artifact,
)


def _tasks():
    return [
        EvalTask("t-001", 1, "prompt one", "exact_match", True, expected="a"),
        EvalTask("t-002", 1, "prompt two", "exact_match", True, expected="b"),
        EvalTask("t-003", 2, "prompt three", "llm_judge", False, rubric="score it"),
    ]


def _record(task_id, category, scoring_type, text="hello", **overrides):
    ref, digest, length = persist_raw_response("test-run", task_id, text)
    base = {
        "task_id": task_id, "category": category, "scoring_type": scoring_type,
        "text_sha256": digest, "byte_length": length, "error": None,
        "latency_ms": 1.0, "raw_response_ref": ref,
    }
    base.update(overrides)
    return base


def _manifest(records, expected_task_ids=("t-001", "t-002", "t-003")):
    return GenerationArtifactManifest(
        schema_version=GENERATION_ARTIFACT_SCHEMA_VERSION, run_id="test-run", candidate="c",
        upstream_model="m", artifact_repo="r", exact_revision="a" * 40, tokenizer_revision="a" * 40,
        suite_id="genesis-eval-test", suite_version="v1", suite_content_digest="x", suite_scoring_contract_digest="y",
        generation_config_digest="sha256:z", system_instruction_digest="sha256:w",
        expected_task_ids=tuple(expected_task_ids), records=tuple(records),
        software_commit_sha="test-sha", backend="dry-run", hardware={}, created_at="2026-09-19T00:00:00Z",
    )


# ── content-addressed durable storage ────────────────────────────────────


def test_persist_raw_response_is_content_addressed_and_readable():
    ref, digest, length = persist_raw_response("run-x", "task-1", "hello world")
    text = read_and_verify_raw_response(ref, digest)
    assert text == "hello world"
    assert length == len("hello world".encode("utf-8"))


def test_read_and_verify_raw_response_rejects_corrupted_content():
    ref, digest, _length = persist_raw_response("run-x", "task-2", "original text")
    from pathlib import Path

    Path(ref).write_text("tampered text")
    with pytest.raises(GenerationArtifactIntegrityError, match="does not match"):
        read_and_verify_raw_response(ref, digest)


def test_read_and_verify_raw_response_rejects_missing_file():
    with pytest.raises(GenerationArtifactIntegrityError, match="does not resolve"):
        read_and_verify_raw_response("/nonexistent/path.txt", "deadbeef")


# ── reconciliation against the verified suite ────────────────────────────


def test_verify_against_suite_passes_for_a_complete_matching_bundle():
    tasks = _tasks()
    records = [_record("t-001", 1, "exact_match"), _record("t-002", 1, "exact_match"), _record("t-003", 2, "llm_judge")]
    verify_against_suite(_manifest(records), tasks)  # must not raise


def test_verify_against_suite_rejects_missing_task():
    tasks = _tasks()
    records = [_record("t-001", 1, "exact_match"), _record("t-003", 2, "llm_judge")]
    with pytest.raises(GenerationArtifactIntegrityError, match="missing"):
        verify_against_suite(_manifest(records), tasks)


def test_verify_against_suite_rejects_duplicate_task():
    tasks = _tasks()
    records = [_record("t-001", 1, "exact_match"), _record("t-001", 1, "exact_match"),
               _record("t-002", 1, "exact_match"), _record("t-003", 2, "llm_judge")]
    with pytest.raises(GenerationArtifactIntegrityError, match="duplicate"):
        verify_against_suite(_manifest(records), tasks)


def test_verify_against_suite_rejects_unknown_task():
    tasks = _tasks()
    records = [_record("t-001", 1, "exact_match"), _record("t-002", 1, "exact_match"),
               _record("t-003", 2, "llm_judge"), _record("t-999-not-real", 1, "exact_match")]
    with pytest.raises(GenerationArtifactIntegrityError, match="unknown"):
        verify_against_suite(_manifest(records), tasks)


def test_verify_against_suite_rejects_category_mismatch():
    tasks = _tasks()
    records = [_record("t-001", 99, "exact_match"), _record("t-002", 1, "exact_match"), _record("t-003", 2, "llm_judge")]
    with pytest.raises(GenerationArtifactIntegrityError, match="mismatched"):
        verify_against_suite(_manifest(records), tasks)


def test_verify_against_suite_rejects_scoring_type_mismatch():
    tasks = _tasks()
    records = [_record("t-001", 1, "pattern_match"), _record("t-002", 1, "exact_match"), _record("t-003", 2, "llm_judge")]
    with pytest.raises(GenerationArtifactIntegrityError, match="mismatched"):
        verify_against_suite(_manifest(records), tasks)


# ── serialization round trip ──────────────────────────────────────────────


def test_manifest_serialization_round_trip_preserves_every_byte():
    tasks = _tasks()
    records = [_record("t-001", 1, "exact_match", text="response with unicode: café"),
               _record("t-002", 1, "exact_match"), _record("t-003", 2, "llm_judge")]
    original = _manifest(records)
    raw = original.to_json()
    restored = GenerationArtifactManifest.from_json(raw)
    assert restored.bundle_digest() == original.bundle_digest()
    assert restored.records == original.records
    assert restored.expected_task_ids == original.expected_task_ids


def test_manifest_from_json_rejects_unsupported_schema_version():
    tasks = _tasks()
    records = [_record("t-001", 1, "exact_match")]
    manifest = _manifest(records)
    import json

    payload = json.loads(manifest.to_json())
    payload["schema_version"] = "some-other-schema-v99"
    with pytest.raises(GenerationArtifactIntegrityError, match="Unsupported"):
        GenerationArtifactManifest.from_json(json.dumps(payload))


# ── end-to-end: generation phase -> artifact -> cross-machine round trip -> scoring ──


def _candidate_config(**overrides):
    defaults = dict(
        candidate="c", upstream_model="m", artifact_repo="r", exact_revision="a" * 40,
        tokenizer_revision="a" * 40, backend="dry-run", quantization="none",
        inference_config={"temperature": 0.0}, seed=42, context_window_used=1024,
        system_instruction="test system instruction", hardware={"gpu": "none"},
    )
    defaults.update(overrides)
    return CandidateConfig(**defaults)


def test_end_to_end_generation_to_artifact_to_scoring_round_trip():
    tasks = _tasks()
    config = _candidate_config()
    records = run_generation_phase(DryRunAdapter(), config, tasks, run_id="e2e-run")
    manifest = build_generation_artifact_manifest(
        records, config, tasks, suite_id="genesis-eval-test", suite_version="v1",
        content_digest="x", scoring_digest="y", run_id="e2e-run", created_at="2026-09-19T00:00:00Z",
    )

    # Simulate crossing a machine boundary: serialize, then deserialize
    # from a fresh object (as a separate scoring-side process would).
    raw = manifest.to_json()
    restored = GenerationArtifactManifest.from_json(raw)

    result, scored_task_ids = run_scoring_phase_from_artifact(
        restored, config, tasks, suite_id="genesis-eval-test", suite_version="v1",
        content_digest="x", scoring_digest="y", started_at="2026-09-19T00:00:00Z",
    )
    assert len(result.per_task_results) == len(tasks)
    assert scored_task_ids  # at least the non-judge tasks were scored


def test_run_scoring_phase_from_artifact_fails_closed_on_dropped_record():
    """The exact scenario the audit was concerned about: a record lost
    in cross-machine transfer must be caught BEFORE scoring runs, not
    silently produce a smaller-but-'complete'-looking result."""
    tasks = _tasks()
    config = _candidate_config()
    records = run_generation_phase(DryRunAdapter(), config, tasks, run_id="drop-run")
    manifest = build_generation_artifact_manifest(
        records, config, tasks, suite_id="genesis-eval-test", suite_version="v1",
        content_digest="x", scoring_digest="y", run_id="drop-run", created_at="2026-09-19T00:00:00Z",
    )
    # Simulate a dropped record during "transfer".
    truncated_records = tuple(r for r in manifest.records if r["task_id"] != "t-002")
    from dataclasses import replace

    truncated_manifest = replace(manifest, records=truncated_records)

    with pytest.raises(GenerationArtifactIntegrityError, match="missing"):
        run_scoring_phase_from_artifact(
            truncated_manifest, config, tasks, suite_id="genesis-eval-test", suite_version="v1",
            content_digest="x", scoring_digest="y", started_at="2026-09-19T00:00:00Z",
        )


def test_run_scoring_phase_from_artifact_fails_closed_on_corrupted_response():
    tasks = _tasks()
    config = _candidate_config()
    records = run_generation_phase(DryRunAdapter(), config, tasks, run_id="corrupt-run")
    manifest = build_generation_artifact_manifest(
        records, config, tasks, suite_id="genesis-eval-test", suite_version="v1",
        content_digest="x", scoring_digest="y", run_id="corrupt-run", created_at="2026-09-19T00:00:00Z",
    )
    # Corrupt the on-disk raw response for one task without touching the manifest's recorded hash.
    from pathlib import Path

    corrupted_ref = None
    for r in manifest.records:
        if r.get("raw_response_ref"):
            corrupted_ref = r["raw_response_ref"]
            break
    assert corrupted_ref is not None
    Path(corrupted_ref).write_text("CORRUPTED CONTENT THAT DOES NOT MATCH THE RECORDED HASH")

    with pytest.raises(GenerationArtifactIntegrityError, match="does not match"):
        run_scoring_phase_from_artifact(
            manifest, config, tasks, suite_id="genesis-eval-test", suite_version="v1",
            content_digest="x", scoring_digest="y", started_at="2026-09-19T00:00:00Z",
        )
