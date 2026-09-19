"""Phase 21B.4.8.1 GenerationArtifactManifest tests -- durable,
content-addressed raw-response storage and fail-closed reconciliation
against the verified suite (never against whatever records happen to
arrive)."""
from __future__ import annotations

import pytest

from orca.eval.generation_artifact import (
    GENERATION_ARTIFACT_SCHEMA_VERSION,
    GenerationArtifactIdentityMismatchError,
    GenerationArtifactIntegrityError,
    GenerationArtifactManifest,
    VerifiedGenerationArtifact,
    load_and_verify_generation_artifact,
    persist_raw_response,
    read_and_verify_raw_response,
    read_sealed_generation_artifact,
    seal_generation_artifact,
    verify_against_suite,
    verify_manifest_identity,
    write_sealed_generation_artifact,
)
from orca.eval.genesis_suite import EvalTask
from orca.eval.runner import (
    CandidateConfig,
    DryRunAdapter,
    RemoteGenerationRecord,
    build_generation_artifact_manifest,
    materialize_generation_artifact,
    run_generation_phase,
    run_remote_generation_phase,
    run_scoring_phase_from_artifact,
    score_verified_generation_artifact,
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


# ── Phase 21B.4.8.2 Blocker 1: remote generation + canonical materialization ──


def test_run_remote_generation_phase_returns_no_local_paths():
    """RemoteGenerationRecord must never carry anything resembling a
    durable artifact path -- the worker is not responsible for deciding
    one."""
    tasks = _tasks()
    config = _candidate_config()
    remote_records = run_remote_generation_phase(DryRunAdapter(), config, tasks)
    assert len(remote_records) == len(tasks)
    for r in remote_records:
        assert isinstance(r, RemoteGenerationRecord)
        assert not hasattr(r, "raw_response_ref")


def test_materialize_generation_artifact_persists_and_builds_manifest():
    tasks = _tasks()
    config = _candidate_config()
    remote_records = run_remote_generation_phase(DryRunAdapter(), config, tasks)
    manifest = materialize_generation_artifact(
        remote_records, config, tasks, suite_id="genesis-eval-test", suite_version="v1",
        content_digest="x", scoring_digest="y", run_id="materialize-run", created_at="2026-09-19T00:00:00Z",
    )
    verify_against_suite(manifest, tasks)  # must not raise
    for r in manifest.records:
        if r["error"] is None:
            assert r["raw_response_ref"] is not None
            read_and_verify_raw_response(r["raw_response_ref"], r["text_sha256"], r["byte_length"])


def test_materialize_generation_artifact_rejects_dropped_remote_record():
    """Attack 17: a remote generation record dropped before
    materialization must fail closed BEFORE anything is persisted."""
    tasks = _tasks()
    config = _candidate_config()
    remote_records = run_remote_generation_phase(DryRunAdapter(), config, tasks)
    truncated = [r for r in remote_records if r.task_id != "t-002"]
    with pytest.raises(GenerationArtifactIntegrityError, match="missing"):
        materialize_generation_artifact(
            truncated, config, tasks, suite_id="genesis-eval-test", suite_version="v1",
            content_digest="x", scoring_digest="y", run_id="materialize-drop", created_at="2026-09-19T00:00:00Z",
        )


def test_materialize_generation_artifact_rejects_duplicate_remote_record():
    """Attack 18: a duplicate remote generation record."""
    tasks = _tasks()
    config = _candidate_config()
    remote_records = run_remote_generation_phase(DryRunAdapter(), config, tasks)
    duplicated = list(remote_records) + [remote_records[0]]
    with pytest.raises(GenerationArtifactIntegrityError, match="duplicate"):
        materialize_generation_artifact(
            duplicated, config, tasks, suite_id="genesis-eval-test", suite_version="v1",
            content_digest="x", scoring_digest="y", run_id="materialize-dup", created_at="2026-09-19T00:00:00Z",
        )


def test_materialize_generation_artifact_rejects_unknown_remote_record():
    """Attack 19: a remote record referencing a task_id not in the suite."""
    tasks = _tasks()
    config = _candidate_config()
    remote_records = run_remote_generation_phase(DryRunAdapter(), config, tasks)
    unknown_record = RemoteGenerationRecord(
        task_id="t-999-not-real", category=1, scoring_type="exact_match", text="x", error=None, latency_ms=1.0,
    )
    with pytest.raises(GenerationArtifactIntegrityError, match="unknown"):
        materialize_generation_artifact(
            list(remote_records) + [unknown_record], config, tasks, suite_id="genesis-eval-test", suite_version="v1",
            content_digest="x", scoring_digest="y", run_id="materialize-unknown", created_at="2026-09-19T00:00:00Z",
        )


def test_full_cross_machine_simulation_different_filesystem_roots(tmp_path, monkeypatch):
    """A real cross-machine simulation: the 'generation worker' produces
    pure in-memory RemoteGenerationRecords (no filesystem at all), the
    'orchestrator' materializes+seals into root A, the sealed BYTES are
    'transferred' (just passed as a Python bytes object -- no shared
    path), and the 'scoring host' verifies+scores using ONLY the
    transferred bytes plus its own re-read of the orchestrator's root.
    Generation-worker filesystem paths are never involved -- the whole
    point being that no raw_response_ref ever pointed anywhere but the
    orchestrator's own canonical store."""
    import orca.eval.generation_artifact as ga_mod

    tasks = _tasks()
    config = _candidate_config()

    # "Generation worker": produces RemoteGenerationRecords with zero
    # filesystem interaction -- this is the entire point of Blocker 1.
    remote_records = run_remote_generation_phase(DryRunAdapter(), config, tasks)
    assert not any(hasattr(r, "raw_response_ref") for r in remote_records)

    # "Orchestrator root": a distinct temp directory, standing in for a
    # completely different machine's ORCA_HOME than any generation-side
    # state.
    orchestrator_root = tmp_path / "orchestrator_root" / "generation_artifacts"
    monkeypatch.setattr(ga_mod, "GENERATION_ARTIFACT_DIR", orchestrator_root)
    manifest = materialize_generation_artifact(
        remote_records, config, tasks, suite_id="genesis-eval-test", suite_version="v1",
        content_digest="x", scoring_digest="y", run_id="xmachine-run", created_at="2026-09-19T00:00:00Z",
    )
    for r in manifest.records:
        if r["raw_response_ref"] is not None:
            assert str(orchestrator_root) in r["raw_response_ref"]

    serialized, digest = seal_generation_artifact(manifest)

    # "Scoring root": raw responses are re-read from the SAME
    # orchestrator_root (a real cross-machine deployment would put this
    # on shared/synced durable storage, or the scoring host would fetch
    # each referenced blob over a transport of the caller's choice) --
    # the point under test is that the manifest transfer itself required
    # nothing but `serialized` bytes plus the independently-retained
    # digest, and required zero knowledge of any generation-worker path.
    verified = load_and_verify_generation_artifact(serialized, digest)
    result, scored_task_ids = score_verified_generation_artifact(
        verified, config, tasks, suite_id="genesis-eval-test", suite_version="v1",
        content_digest="x", scoring_digest="y", started_at="2026-09-19T00:00:00Z",
    )
    assert len(result.per_task_results) == len(tasks)
    assert scored_task_ids
    assert result.provenance_kind == "real_generation_artifact"
    assert result.generation_artifact_digest == digest


# ── Phase 21B.4.8.2 Blocker 2: identity binding ──────────────────────────


def _sealed_manifest_for_scoring(tasks, config, *, run_id="identity-run"):
    records = run_generation_phase(DryRunAdapter(), config, tasks, run_id=run_id)
    manifest = build_generation_artifact_manifest(
        records, config, tasks, suite_id="genesis-eval-test", suite_version="v1",
        content_digest="x", scoring_digest="y", run_id=run_id, created_at="2026-09-19T00:00:00Z",
    )
    return manifest


def test_verify_manifest_identity_passes_for_matching_config():
    tasks = _tasks()
    config = _candidate_config()
    manifest = _sealed_manifest_for_scoring(tasks, config)
    verify_manifest_identity(
        manifest, config, tasks, suite_id="genesis-eval-test", suite_version="v1",
        content_digest="x", scoring_digest="y",
    )  # must not raise


def test_identity_mismatch_candidate_a_artifact_scored_as_candidate_b():
    """Attack 1: generate with candidate A, attempt to score with
    candidate B's CandidateConfig -- must fail before scoring."""
    tasks = _tasks()
    config_a = _candidate_config(candidate="candidate-a")
    manifest = _sealed_manifest_for_scoring(tasks, config_a)
    config_b = _candidate_config(candidate="candidate-b")
    with pytest.raises(GenerationArtifactIdentityMismatchError, match="candidate"):
        run_scoring_phase_from_artifact(
            manifest, config_b, tasks, suite_id="genesis-eval-test", suite_version="v1",
            content_digest="x", scoring_digest="y", started_at="2026-09-19T00:00:00Z",
        )


def test_identity_mismatch_revision_a_artifact_scored_as_revision_b():
    """Attack 2: outputs from revision X must not be scoreable as
    revision Y."""
    tasks = _tasks()
    config_x = _candidate_config(exact_revision="a" * 40)
    manifest = _sealed_manifest_for_scoring(tasks, config_x)
    config_y = _candidate_config(exact_revision="b" * 40)
    with pytest.raises(GenerationArtifactIdentityMismatchError, match="exact_revision"):
        run_scoring_phase_from_artifact(
            manifest, config_y, tasks, suite_id="genesis-eval-test", suite_version="v1",
            content_digest="x", scoring_digest="y", started_at="2026-09-19T00:00:00Z",
        )


def test_identity_mismatch_tokenizer_revision():
    """Attack 3: tokenizer revision mismatch."""
    tasks = _tasks()
    config_x = _candidate_config(tokenizer_revision="a" * 40)
    manifest = _sealed_manifest_for_scoring(tasks, config_x)
    config_y = _candidate_config(tokenizer_revision="c" * 40)
    with pytest.raises(GenerationArtifactIdentityMismatchError, match="tokenizer_revision"):
        run_scoring_phase_from_artifact(
            manifest, config_y, tasks, suite_id="genesis-eval-test", suite_version="v1",
            content_digest="x", scoring_digest="y", started_at="2026-09-19T00:00:00Z",
        )


def test_identity_mismatch_artifact_repo():
    """Attack 4: artifact repo mismatch."""
    tasks = _tasks()
    config_x = _candidate_config(artifact_repo="repo-x")
    manifest = _sealed_manifest_for_scoring(tasks, config_x)
    config_y = _candidate_config(artifact_repo="repo-y")
    with pytest.raises(GenerationArtifactIdentityMismatchError, match="artifact_repo"):
        run_scoring_phase_from_artifact(
            manifest, config_y, tasks, suite_id="genesis-eval-test", suite_version="v1",
            content_digest="x", scoring_digest="y", started_at="2026-09-19T00:00:00Z",
        )


def test_identity_mismatch_backend():
    """Attack 5: backend mismatch."""
    tasks = _tasks()
    config_x = _candidate_config(backend="dry-run")
    manifest = _sealed_manifest_for_scoring(tasks, config_x)
    config_y = _candidate_config(backend="vllm")
    with pytest.raises(GenerationArtifactIdentityMismatchError, match="backend"):
        run_scoring_phase_from_artifact(
            manifest, config_y, tasks, suite_id="genesis-eval-test", suite_version="v1",
            content_digest="x", scoring_digest="y", started_at="2026-09-19T00:00:00Z",
        )


def test_identity_mismatch_generation_config():
    """Attack 6: generation-config mismatch (inference_config digest)."""
    tasks = _tasks()
    config_x = _candidate_config(inference_config={"temperature": 0.0})
    manifest = _sealed_manifest_for_scoring(tasks, config_x)
    config_y = _candidate_config(inference_config={"temperature": 0.9})
    with pytest.raises(GenerationArtifactIdentityMismatchError, match="generation_config_digest"):
        run_scoring_phase_from_artifact(
            manifest, config_y, tasks, suite_id="genesis-eval-test", suite_version="v1",
            content_digest="x", scoring_digest="y", started_at="2026-09-19T00:00:00Z",
        )


def test_identity_mismatch_system_instruction():
    """Attack 7: system-instruction mismatch."""
    tasks = _tasks()
    config_x = _candidate_config(system_instruction="instruction A")
    manifest = _sealed_manifest_for_scoring(tasks, config_x)
    config_y = _candidate_config(system_instruction="instruction B")
    with pytest.raises(GenerationArtifactIdentityMismatchError, match="system_instruction_digest"):
        run_scoring_phase_from_artifact(
            manifest, config_y, tasks, suite_id="genesis-eval-test", suite_version="v1",
            content_digest="x", scoring_digest="y", started_at="2026-09-19T00:00:00Z",
        )


def test_identity_mismatch_suite_id():
    """Attack 8: suite ID mismatch."""
    tasks = _tasks()
    config = _candidate_config()
    manifest = _sealed_manifest_for_scoring(tasks, config)
    with pytest.raises(GenerationArtifactIdentityMismatchError, match="suite_id"):
        run_scoring_phase_from_artifact(
            manifest, config, tasks, suite_id="a-totally-different-suite", suite_version="v1",
            content_digest="x", scoring_digest="y", started_at="2026-09-19T00:00:00Z",
        )


def test_identity_mismatch_suite_version():
    """Attack 9: suite version mismatch."""
    tasks = _tasks()
    config = _candidate_config()
    manifest = _sealed_manifest_for_scoring(tasks, config)
    with pytest.raises(GenerationArtifactIdentityMismatchError, match="suite_version"):
        run_scoring_phase_from_artifact(
            manifest, config, tasks, suite_id="genesis-eval-test", suite_version="v2",
            content_digest="x", scoring_digest="y", started_at="2026-09-19T00:00:00Z",
        )


def test_identity_mismatch_suite_content_digest():
    """Attack 10: suite-content-digest mismatch."""
    tasks = _tasks()
    config = _candidate_config()
    manifest = _sealed_manifest_for_scoring(tasks, config)
    with pytest.raises(GenerationArtifactIdentityMismatchError, match="suite_content_digest"):
        run_scoring_phase_from_artifact(
            manifest, config, tasks, suite_id="genesis-eval-test", suite_version="v1",
            content_digest="a-different-content-digest", scoring_digest="y", started_at="2026-09-19T00:00:00Z",
        )


def test_identity_mismatch_scoring_contract_digest():
    """Attack 11: scoring-contract-digest mismatch."""
    tasks = _tasks()
    config = _candidate_config()
    manifest = _sealed_manifest_for_scoring(tasks, config)
    with pytest.raises(GenerationArtifactIdentityMismatchError, match="suite_scoring_contract_digest"):
        run_scoring_phase_from_artifact(
            manifest, config, tasks, suite_id="genesis-eval-test", suite_version="v1",
            content_digest="x", scoring_digest="a-different-scoring-digest", started_at="2026-09-19T00:00:00Z",
        )


def test_identity_mismatch_expected_task_ids():
    """Attack 12: expected_task_ids mismatch -- the manifest claims a
    different task set than the live-verified suite actually has."""
    tasks = _tasks()
    config = _candidate_config()
    manifest = _sealed_manifest_for_scoring(tasks, config)
    from dataclasses import replace

    tampered = replace(manifest, expected_task_ids=("t-001", "t-002", "t-999-different"))
    with pytest.raises(GenerationArtifactIdentityMismatchError, match="expected_task_ids"):
        run_scoring_phase_from_artifact(
            tampered, config, tasks, suite_id="genesis-eval-test", suite_version="v1",
            content_digest="x", scoring_digest="y", started_at="2026-09-19T00:00:00Z",
        )


# ── Phase 21B.4.8.2 Blocker 3: sealing / verified transfer ───────────────


def test_seal_and_load_verify_round_trip():
    tasks = _tasks()
    config = _candidate_config()
    manifest = _sealed_manifest_for_scoring(tasks, config, run_id="seal-round-trip")
    serialized, digest = seal_generation_artifact(manifest)
    verified = load_and_verify_generation_artifact(serialized, digest)
    assert verified.bundle_digest == digest
    assert verified.schema_version == manifest.schema_version
    assert verified.manifest.bundle_digest() == manifest.bundle_digest()


def test_load_and_verify_generation_artifact_returns_a_verified_receipt_not_a_bare_manifest():
    """The receipt type itself (Phase 21B.4.8.3 section 5) -- not a
    GenerationArtifactManifest, and not directly constructible by a
    caller without going through load_and_verify_generation_artifact()."""
    tasks = _tasks()
    config = _candidate_config()
    manifest = _sealed_manifest_for_scoring(tasks, config, run_id="seal-receipt-type")
    serialized, digest = seal_generation_artifact(manifest)
    verified = load_and_verify_generation_artifact(serialized, digest)
    assert isinstance(verified, VerifiedGenerationArtifact)
    assert not isinstance(verified, GenerationArtifactManifest)
    with pytest.raises(TypeError, match="load_and_verify_generation_artifact"):
        VerifiedGenerationArtifact(
            manifest=manifest, bundle_digest=digest, schema_version=manifest.schema_version,
            verified_at="2026-09-19T00:00:00Z", proof="not a real proof",
        )


def test_write_and_read_sealed_generation_artifact_round_trip():
    tasks = _tasks()
    config = _candidate_config()
    manifest = _sealed_manifest_for_scoring(tasks, config, run_id="seal-write-read")
    json_path, digest_path, digest = write_sealed_generation_artifact(manifest)
    assert json_path.exists()
    assert digest_path.exists()
    serialized, expected_digest = read_sealed_generation_artifact("seal-write-read")
    assert expected_digest == digest
    verified = load_and_verify_generation_artifact(serialized, expected_digest)
    assert verified.manifest.run_id == manifest.run_id


def test_attack_13_bundle_json_altered_after_sealing_is_rejected():
    tasks = _tasks()
    config = _candidate_config()
    manifest = _sealed_manifest_for_scoring(tasks, config, run_id="seal-tamper-bytes")
    serialized, digest = seal_generation_artifact(manifest)
    tampered = serialized.replace(b'"candidate":"c"', b'"candidate":"z"')
    assert tampered != serialized  # sanity: the tamper actually changed something
    with pytest.raises(GenerationArtifactIntegrityError, match="digest mismatch"):
        load_and_verify_generation_artifact(tampered, digest)


def test_attack_14_expected_digest_altered_is_rejected():
    tasks = _tasks()
    config = _candidate_config()
    manifest = _sealed_manifest_for_scoring(tasks, config, run_id="seal-tamper-digest")
    serialized, digest = seal_generation_artifact(manifest)
    wrong_digest = "0" * 64
    assert wrong_digest != digest
    with pytest.raises(GenerationArtifactIntegrityError, match="digest mismatch"):
        load_and_verify_generation_artifact(serialized, wrong_digest)


def test_attack_15_raw_response_bytes_altered_is_rejected():
    ref, digest, length = persist_raw_response("attack15-run", "task-a", "original bytes")
    from pathlib import Path

    Path(ref).write_bytes(b"altered bytes!!")
    with pytest.raises(GenerationArtifactIntegrityError, match="does not match"):
        read_and_verify_raw_response(ref, digest, length)


def test_attack_16_raw_response_byte_length_mismatch_is_rejected():
    ref, digest, length = persist_raw_response("attack16-run", "task-a", "some original text")
    with pytest.raises(GenerationArtifactIntegrityError, match="byte_length"):
        read_and_verify_raw_response(ref, digest, length + 5)
