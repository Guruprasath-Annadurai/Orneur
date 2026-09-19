"""
Phase 21B.4 (§2) baseline<->freeze transaction tests -- orca.eval.baseline
.record_baseline_and_freeze_suite(), the fail-closed coupling between
recording a real candidate result and freezing genesis-eval-v1. These
tests exercise REAL behavior against isolated temp registry directories
(via tests/conftest.py's autouse fixture), never merely asserting
comments/docstrings.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from orca.eval.baseline import (
    BaselineFreezeFailed,
    BaselineIntegrityError,
    DuplicateRunIdError,
    GenerationArtifactMismatchError,
    GenerationArtifactMissingError,
    IncompleteResultError,
    MissingGenerationProvenanceError,
    record_baseline_and_freeze_suite,
)
from orca.eval.generation_artifact import (
    GENERATION_ARTIFACT_SCHEMA_VERSION,
    GenerationArtifactManifest,
    load_and_verify_generation_artifact,
    persist_raw_response,
    read_sealed_generation_artifact,
    write_sealed_generation_artifact,
)
from orca.eval.genesis_suite import EvalTask, all_tasks, compute_suite_digests
from orca.eval.runner import (
    CandidateConfig,
    DryRunAdapter,
    materialize_generation_artifact,
    run_remote_generation_phase,
    run_suite,
    score_verified_generation_artifact,
)
from orca.registry.evaluation_result_manifest import EvaluationResultManifest
from orca.registry.evaluation_suite_manifest import EvaluationSuiteManifest


def _tiny_task_set() -> list[EvalTask]:
    """A small, cheap-to-work-with task list for transaction tests --
    real EvalTask objects, not a mock, exercising the real
    compute_suite_digests()/verify_against_tasks() code paths."""
    return [
        EvalTask("t-001", 1, "prompt one", "exact_match", True, expected="a"),
        EvalTask("t-002", 1, "prompt two", "exact_match", True, expected="b"),
        EvalTask("t-003", 2, "prompt three", "llm_judge", False, rubric="score it"),
    ]


def _seal_matching_artifact(result: EvaluationResultManifest, tasks: list[EvalTask]) -> str:
    """Builds and persists a sealed GenerationArtifactManifest whose
    IDENTITY fields exactly match `result` -- the fixture equivalent of
    a real score_verified_generation_artifact() run, so most existing
    tests (which are not specifically about provenance) can exercise
    record_baseline_and_freeze_suite()'s now-mandatory real-provenance
    gate (Phase 21B.4.8.3) without needing a full DryRunAdapter pipeline.
    `records` is built to match `tasks` exactly (Phase 21B.4.10: the
    mandatory pre-freeze raw-evidence gate now re-runs
    verify_against_suite() AND independently re-verifies each
    successful record's raw-response file at finalization time, so an
    empty/fabricated records list -- sufficient before that gate existed
    -- would now correctly be rejected as incomplete). Each task with a
    per_task_results entry gets a real persisted raw response (content
    doesn't matter -- baseline-level checks are structural, not content-
    aware); each task with a generation_failures entry gets an explicit
    error record. Returns the bundle digest."""
    import hashlib
    import json

    generation_config_digest = "sha256:" + hashlib.sha256(
        json.dumps(result.inference_config, sort_keys=True).encode("utf-8")
    ).hexdigest()

    failed_task_ids = {e["task_id"] for e in result.generation_failures}
    records = []
    for t in tasks:
        if t.task_id in failed_task_ids:
            records.append({
                "task_id": t.task_id, "category": t.category, "scoring_type": t.scoring_type,
                "text_sha256": None, "byte_length": None, "error": "simulated backend failure",
                "latency_ms": 1.0, "raw_response_ref": None,
            })
            continue
        ref, digest, length = persist_raw_response(result.run_id, t.task_id, f"fixture response for {t.task_id}")
        records.append({
            "task_id": t.task_id, "category": t.category, "scoring_type": t.scoring_type,
            "text_sha256": digest, "byte_length": length, "error": None,
            "latency_ms": 1.0, "raw_response_ref": ref,
        })

    manifest = GenerationArtifactManifest(
        schema_version=GENERATION_ARTIFACT_SCHEMA_VERSION,
        run_id=result.run_id, candidate=result.candidate,
        upstream_model=result.upstream_model, artifact_repo=result.artifact_repo,
        exact_revision=result.exact_revision, tokenizer_revision=result.tokenizer_revision,
        suite_id=result.suite_id, suite_version=result.suite_version,
        suite_content_digest=result.suite_content_digest, suite_scoring_contract_digest=result.suite_scoring_contract_digest,
        generation_config_digest=generation_config_digest,
        system_instruction_digest=result.system_instruction_digest,
        expected_task_ids=tuple(t.task_id for t in tasks), records=tuple(records),
        software_commit_sha=result.software_commit_sha, backend=result.backend,
        hardware=dict(result.hardware), created_at=result.started_at,
    )
    _json_path, _digest_path, digest = write_sealed_generation_artifact(manifest)
    return digest


def _make_result(
    tasks: list[EvalTask], *, run_id: str, complete: bool = True,
    candidate: str = "test-candidate", suite_id: str = "genesis-eval-test",
) -> tuple[EvaluationResultManifest, list[str]]:
    task_ids, content_digest, scoring_digest = compute_suite_digests(tasks)
    scored_task_ids = [t.task_id for t in tasks if t.scoring_type != "llm_judge"]
    judge_task_ids = [t.task_id for t in tasks if t.scoring_type == "llm_judge"]
    # Phase 21B.4.8.1: denominator-integrity now requires EVERY suite
    # task (including llm_judge ones) to appear in per_task_results or
    # generation_failures -- matching orca.eval.runner.run_scoring_phase()'s
    # real contract, which adds an explicit unscored-marker entry for
    # judge tasks rather than omitting them.
    per_task = [{"task_id": tid, "passed": True} for tid in scored_task_ids] if complete else []
    if complete:
        per_task += [{"task_id": tid, "passed": None, "note": "UNSCORED_REQUIRES_JUDGE"} for tid in judge_task_ids]
    result = EvaluationResultManifest(
        run_id=run_id, candidate=candidate, upstream_model="test/model",
        artifact_repo="test/model", exact_revision="abc123", tokenizer_revision="abc123",
        backend="test-backend", quantization="none", inference_config={"temperature": 0.0},
        seed=42, context_window_used=1024, system_instruction_digest="sha256:deadbeef",
        software_commit_sha="test-sha", hardware={"gpu": "none"},
        suite_id=suite_id, suite_version="v1",
        suite_content_digest=content_digest, suite_scoring_contract_digest=scoring_digest,
        per_task_results=per_task, unscored_categories=["2"],
        completed_at="2026-09-18T00:00:00Z" if complete else None,
    )
    # Phase 21B.4.8.3: record_baseline_and_freeze_suite() now REQUIRES
    # provenance_kind="real_generation_artifact" plus a digest that
    # re-verifies against an actual sealed artifact on disk -- seal a
    # matching one by default so every pre-existing test in this file
    # (which is not specifically testing provenance) keeps working
    # unchanged. Tests that specifically exercise the provenance gate
    # override these fields (or the sealed artifact) afterward.
    if complete:
        digest = _seal_matching_artifact(result, tasks)
        result.provenance_kind = "real_generation_artifact"
        result.generation_artifact_digest = digest
        result.generation_artifact_schema_version = GENERATION_ARTIFACT_SCHEMA_VERSION
    return result, scored_task_ids


# ── 1. unfrozen suite can be authored before any baseline exists ──────────


def test_unfrozen_suite_can_be_authored_before_any_baseline():
    tasks = _tiny_task_set()
    task_ids, content_digest, scoring_digest = compute_suite_digests(tasks)
    manifest = EvaluationSuiteManifest(
        suite_id="genesis-eval-test", version="v1", task_ids=task_ids,
        content_digest=content_digest, scoring_contract_digest=scoring_digest, creation_code_sha="sha",
    )
    manifest.save()
    reloaded = EvaluationSuiteManifest.load("genesis-eval-test", "v1")
    assert reloaded.frozen is False


# ── 2/3. digest mismatches reject evaluation ────────────────────────────


def test_content_digest_mismatch_rejects_before_freeze():
    tasks = _tiny_task_set()
    result, scored_ids = _make_result(tasks, run_id="run-content-mismatch")
    result.suite_content_digest = "wrong-digest"
    with pytest.raises(BaselineIntegrityError, match="content_digest"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")
    with pytest.raises(FileNotFoundError):
        EvaluationSuiteManifest.load("genesis-eval-test", "v1")


def test_scoring_contract_digest_mismatch_rejects_before_freeze():
    tasks = _tiny_task_set()
    result, scored_ids = _make_result(tasks, run_id="run-scoring-mismatch")
    result.suite_scoring_contract_digest = "wrong-digest"
    with pytest.raises(BaselineIntegrityError, match="scoring_contract_digest"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")


# ── 4/5. incomplete or failed evaluation cannot freeze the suite ──────────


def test_incomplete_result_cannot_freeze_suite():
    tasks = _tiny_task_set()
    result, scored_ids = _make_result(tasks, run_id="run-incomplete", complete=False)
    with pytest.raises(IncompleteResultError):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")
    with pytest.raises(FileNotFoundError):
        EvaluationResultManifest.load("run-incomplete")
    with pytest.raises(FileNotFoundError):
        EvaluationSuiteManifest.load("genesis-eval-test", "v1")


def test_missing_completed_at_counts_as_failed_evaluation():
    tasks = _tiny_task_set()
    result, scored_ids = _make_result(tasks, run_id="run-no-completed-at")
    result.completed_at = None
    with pytest.raises(IncompleteResultError, match="did not finish"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")


# ── 6/7/8. first valid baseline freezes the suite; persists; survives reload ──


def test_first_valid_baseline_freezes_the_suite_and_persists():
    tasks = _tiny_task_set()
    result, scored_ids = _make_result(tasks, run_id="run-first-baseline")
    finalized = record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")
    assert finalized.finalized is True
    assert finalized.is_first_baseline is True

    reloaded_result = EvaluationResultManifest.load("run-first-baseline")
    assert reloaded_result.finalized is True

    reloaded_suite = EvaluationSuiteManifest.load("genesis-eval-test", "v1")
    assert reloaded_suite.frozen is True
    assert reloaded_suite.frozen_at is not None


# ── 9. frozen suite cannot be overwritten ──────────────────────────────────


def test_frozen_suite_cannot_be_overwritten_directly():
    tasks = _tiny_task_set()
    result, scored_ids = _make_result(tasks, run_id="run-freeze-for-overwrite-test")
    record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")

    from orca.registry.evaluation_suite_manifest import EvaluationSuiteFrozenError

    tampered = EvaluationSuiteManifest(
        suite_id="genesis-eval-test", version="v1", task_ids=["t-999"],
        content_digest="tampered", scoring_contract_digest="tampered", creation_code_sha="sha",
    )
    with pytest.raises(EvaluationSuiteFrozenError):
        tampered.save()


# ── 10/11. task or scoring-contract mutation after freeze is detected ─────


def test_task_mutation_after_freeze_is_detected():
    tasks = _tiny_task_set()
    result, scored_ids = _make_result(tasks, run_id="run-freeze-then-mutate-content")
    record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")

    mutated_tasks = [replace(t, prompt=t.prompt + " (mutated)") if t.task_id == "t-001" else t for t in tasks]
    result2, scored_ids2 = _make_result(mutated_tasks, run_id="run-after-content-mutation")
    with pytest.raises(BaselineIntegrityError, match="does not match"):
        record_baseline_and_freeze_suite(tasks=mutated_tasks, result=result2, scored_task_ids=scored_ids2, suite_id="genesis-eval-test")


def test_scoring_contract_mutation_after_freeze_is_detected():
    tasks = _tiny_task_set()
    result, scored_ids = _make_result(tasks, run_id="run-freeze-then-mutate-scoring")
    record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")

    mutated_tasks = [replace(t, expected="DIFFERENT") if t.task_id == "t-001" else t for t in tasks]
    result2, scored_ids2 = _make_result(mutated_tasks, run_id="run-after-scoring-mutation")
    with pytest.raises(BaselineIntegrityError, match="does not match"):
        record_baseline_and_freeze_suite(tasks=mutated_tasks, result=result2, scored_task_ids=scored_ids2, suite_id="genesis-eval-test")


# ── 12. second candidate may evaluate against frozen v1 if digests still match ──


def test_second_candidate_can_evaluate_against_frozen_suite_with_matching_digests():
    tasks = _tiny_task_set()
    result1, scored_ids = _make_result(tasks, run_id="run-candidate-1")
    record_baseline_and_freeze_suite(tasks=tasks, result=result1, scored_task_ids=scored_ids, suite_id="genesis-eval-test")

    result2, scored_ids2 = _make_result(tasks, run_id="run-candidate-2")
    finalized2 = record_baseline_and_freeze_suite(tasks=tasks, result=result2, scored_task_ids=scored_ids2, suite_id="genesis-eval-test")
    assert finalized2.finalized is True
    assert finalized2.is_first_baseline is False  # did NOT re-trigger a freeze

    suite = EvaluationSuiteManifest.load("genesis-eval-test", "v1")
    assert suite.frozen is True  # unchanged, still frozen from the first baseline


# ── 13. no code path silently regenerates/replaces v1 after freeze ────────


def test_no_path_regenerates_suite_after_freeze_even_on_reregistration_attempt():
    tasks = _tiny_task_set()
    result1, scored_ids = _make_result(tasks, run_id="run-freeze-first")
    record_baseline_and_freeze_suite(tasks=tasks, result=result1, scored_task_ids=scored_ids, suite_id="genesis-eval-test")
    frozen_digest_before = EvaluationSuiteManifest.load("genesis-eval-test", "v1").content_digest

    # A second call with the IDENTICAL (unmutated) task list must not
    # attempt to regenerate/re-save the suite -- it takes the read-only path.
    result2, scored_ids2 = _make_result(tasks, run_id="run-no-regenerate")
    record_baseline_and_freeze_suite(tasks=tasks, result=result2, scored_task_ids=scored_ids2, suite_id="genesis-eval-test")

    frozen_digest_after = EvaluationSuiteManifest.load("genesis-eval-test", "v1").content_digest
    assert frozen_digest_before == frozen_digest_after


# ── 14. result digest references exactly match suite digests ─────────────


def test_finalized_result_digests_exactly_match_suite_digests():
    tasks = _tiny_task_set()
    result, scored_ids = _make_result(tasks, run_id="run-digest-match-check")
    finalized = record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")
    suite = EvaluationSuiteManifest.load("genesis-eval-test", "v1")
    assert finalized.suite_content_digest == suite.content_digest
    assert finalized.suite_scoring_contract_digest == suite.scoring_contract_digest


# ── 15/16. persistence/freeze failure never leaves a falsely-valid state ──


def test_freeze_persistence_failure_rolls_back_staged_result(monkeypatch):
    """Simulates the freeze-save step failing (e.g. a disk error) after
    the result has already been staged -- the staged result must be
    deleted, not left looking like a valid finalized baseline."""
    tasks = _tiny_task_set()
    result, scored_ids = _make_result(tasks, run_id="run-freeze-save-fails")

    import orca.registry.evaluation_suite_manifest as suite_mod

    original_save = suite_mod.EvaluationSuiteManifest.save
    call_count = {"n": 0}

    def _flaky_save(self):
        call_count["n"] += 1
        if call_count["n"] == 2:  # first save = initial unfrozen registration; second = the freeze save
            raise OSError("simulated disk failure during freeze save")
        return original_save(self)

    monkeypatch.setattr(suite_mod.EvaluationSuiteManifest, "save", _flaky_save)

    from orca.eval.baseline import BaselineFreezeFailed as _BFF

    with pytest.raises(_BFF):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")

    with pytest.raises(FileNotFoundError):
        EvaluationResultManifest.load("run-freeze-save-fails")


def test_freeze_reload_verification_failure_rolls_back_staged_result(monkeypatch):
    """Simulates freeze.save() succeeding but the immediate re-read
    verification finding frozen=False (e.g. a torn write) -- must still
    roll back rather than trust the in-memory object."""
    tasks = _tiny_task_set()
    result, scored_ids = _make_result(tasks, run_id="run-reload-verification-fails")

    import orca.registry.evaluation_suite_manifest as suite_mod

    original_load = suite_mod.EvaluationSuiteManifest.load

    def _load_returns_unfrozen(suite_id, version):
        loaded = original_load(suite_id, version)
        loaded.frozen = False  # simulate a torn/incomplete write on reload
        return loaded

    monkeypatch.setattr(suite_mod.EvaluationSuiteManifest, "load", staticmethod(_load_returns_unfrozen))

    with pytest.raises(BaselineFreezeFailed, match="frozen=True"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")

    with pytest.raises(FileNotFoundError):
        EvaluationResultManifest.load("run-reload-verification-fails")


# ── Phase 21B.4.1 (§15) adversarial re-review: real bugs found and fixed ──


def test_result_referencing_wrong_suite_is_rejected():
    """Reproduced live during this closure: a result claiming
    suite_id="totally-different-suite" was previously accepted and
    finalized while the CORRECT suite (per the function's own suite_id
    parameter) was frozen underneath it -- the function never
    cross-checked result.suite_id/suite_version against its own
    parameters. Now rejected explicitly."""
    tasks = _tiny_task_set()
    result, scored_ids = _make_result(tasks, run_id="run-wrong-suite-ref")
    result.suite_id = "totally-different-suite"
    with pytest.raises(BaselineIntegrityError, match="does not match the suite"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")
    with pytest.raises(FileNotFoundError):
        EvaluationResultManifest.load("run-wrong-suite-ref")


def test_result_referencing_wrong_suite_version_is_rejected():
    tasks = _tiny_task_set()
    result, scored_ids = _make_result(tasks, run_id="run-wrong-suite-version-ref")
    result.suite_version = "v99"
    with pytest.raises(BaselineIntegrityError, match="does not match the suite"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")


def test_duplicate_run_id_across_different_candidates_is_rejected():
    """Reproduced live during this closure: reusing a run_id across two
    different candidates silently overwrote the first (already-
    finalized) result with the second's data, with no error at all."""
    tasks = _tiny_task_set()
    result_a, scored_ids_a = _make_result(tasks, run_id="shared-run-id", candidate="candidate-A")
    record_baseline_and_freeze_suite(tasks=tasks, result=result_a, scored_task_ids=scored_ids_a, suite_id="genesis-eval-test")

    result_b, scored_ids_b = _make_result(tasks, run_id="shared-run-id", candidate="candidate-B")
    with pytest.raises(DuplicateRunIdError):
        record_baseline_and_freeze_suite(tasks=tasks, result=result_b, scored_task_ids=scored_ids_b, suite_id="genesis-eval-test")

    reloaded = EvaluationResultManifest.load("shared-run-id")
    assert reloaded.candidate == "candidate-A"  # never overwritten


def test_pre_existing_malformed_result_file_does_not_corrupt_the_transaction(tmp_path, monkeypatch):
    """A pre-existing, malformed (not valid JSON) file at the target
    run_id's path must not crash the transaction in a way that leaves
    ambiguous state -- EvaluationResultManifest.load() raising a
    JSONDecodeError should surface clearly, not be silently swallowed."""
    tasks = _tiny_task_set()
    result, scored_ids = _make_result(tasks, run_id="run-preexisting-malformed")

    from orca.registry.evaluation_result_manifest import EVALUATION_RESULT_DIR

    malformed_path = EVALUATION_RESULT_DIR / "run-preexisting-malformed.json"
    malformed_path.write_text("NOT VALID JSON")

    import json

    with pytest.raises(json.JSONDecodeError):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")


def test_pre_existing_malformed_suite_manifest_surfaces_clearly(tmp_path, monkeypatch):
    tasks = _tiny_task_set()
    result, scored_ids = _make_result(tasks, run_id="run-malformed-suite")

    from orca.registry.evaluation_suite_manifest import EVALUATION_SUITE_DIR

    malformed_path = EVALUATION_SUITE_DIR / "genesis-eval-test-v1.json"
    malformed_path.write_text("NOT VALID JSON")

    import json

    with pytest.raises(json.JSONDecodeError):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")


# ── Phase 21B.4.1 (§16) concurrency hardening ──────────────────────────────


def test_concurrent_baseline_attempts_never_both_believe_they_froze_first():
    """Two threads racing to record the FIRST baseline against the same
    (unfrozen) suite: with the per-suite-version lock, exactly one must
    succeed with is_first_baseline=True and the other must observe the
    suite already frozen (is_first_baseline=False) or a clean rejection
    -- never both succeeding as "first", and never a corrupted suite
    manifest."""
    import threading

    tasks = _tiny_task_set()
    results: dict[str, object] = {}
    errors: dict[str, Exception] = {}

    def _attempt(label: str, run_id: str):
        try:
            result, scored_ids = _make_result(tasks, run_id=run_id, suite_id="genesis-eval-concurrency-test")
            finalized = record_baseline_and_freeze_suite(
                tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-concurrency-test",
            )
            results[label] = finalized
        except Exception as exc:  # pragma: no cover - captured for assertion, not swallowed silently
            errors[label] = exc

    t1 = threading.Thread(target=_attempt, args=("t1", "run-concurrent-1"))
    t2 = threading.Thread(target=_attempt, args=("t2", "run-concurrent-2"))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert not errors, f"unexpected errors: {errors}"
    assert len(results) == 2
    first_baseline_flags = [r.is_first_baseline for r in results.values()]
    # Exactly one of the two concurrent attempts is the "first baseline"
    # that actually froze the suite -- never both, never neither.
    assert sorted(first_baseline_flags) == [False, True]

    from orca.registry.evaluation_suite_manifest import EvaluationSuiteManifest

    suite = EvaluationSuiteManifest.load("genesis-eval-concurrency-test", "v1")
    assert suite.frozen is True


# ── Phase 21B.4.8.1: denominator-integrity adversarial tests ────────────
# "Expected" must come ONLY from the verified suite `tasks`, never from
# scored_task_ids or whatever records happen to be present -- these
# prove that dropping/duplicating/adding records is caught BEFORE any
# baseline can be recorded, regardless of what scored_task_ids claims.


def test_missing_deterministic_record_is_rejected_even_if_scored_task_ids_claims_complete():
    tasks = _tiny_task_set()
    result, scored_ids = _make_result(tasks, run_id="run-missing-det")
    # Simulate a dropped record: remove t-002's entry from per_task_results
    # but leave scored_task_ids claiming both t-001 and t-002 were scored --
    # exactly the cross-machine-transport-loss scenario the audit found.
    result.per_task_results = [e for e in result.per_task_results if e["task_id"] != "t-002"]
    with pytest.raises(IncompleteResultError, match="missing"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")


def test_missing_judge_record_is_rejected():
    tasks = _tiny_task_set()
    result, scored_ids = _make_result(tasks, run_id="run-missing-judge")
    result.per_task_results = [e for e in result.per_task_results if e["task_id"] != "t-003"]
    with pytest.raises(IncompleteResultError, match="missing"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")


def test_duplicate_task_record_is_rejected():
    tasks = _tiny_task_set()
    result, scored_ids = _make_result(tasks, run_id="run-duplicate")
    result.per_task_results = result.per_task_results + [{"task_id": "t-001", "passed": True}]
    with pytest.raises(IncompleteResultError, match="duplicate"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")


def test_unknown_task_record_is_rejected():
    tasks = _tiny_task_set()
    result, scored_ids = _make_result(tasks, run_id="run-unknown")
    result.per_task_results = result.per_task_results + [{"task_id": "t-does-not-exist-in-suite", "passed": True}]
    with pytest.raises(IncompleteResultError, match="unknown"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")


def test_generation_failure_correctly_accounts_for_a_task():
    """A real generation failure (task attempted, model/backend failed)
    is legitimate -- it must be accepted as accounting for the task,
    not treated as a missing/integrity error, since it IS a known,
    explicit outcome, unlike silently-dropped transport data."""
    tasks = _tiny_task_set()
    result, scored_ids = _make_result(tasks, run_id="run-gen-failure")
    result.per_task_results = [e for e in result.per_task_results if e["task_id"] != "t-002"]
    result.generation_failures = [{"task_id": "t-002", "category": 1, "reason": "backend timeout", "latency_ms": 5000.0}]
    finalized = record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")
    assert finalized.finalized is True


# ── Phase 21B.4.8.3: real-baseline provenance ENFORCEMENT ────────────────
# record_baseline_and_freeze_suite() now REQUIRES provenance_kind ==
# "real_generation_artifact" AND independently re-verifies the actual
# sealed artifact on disk at finalization time -- a bare digest string,
# "synthetic_test", or the backward-compatible "unspecified" default are
# all rejected outright. Legacy manifests with provenance_kind=
# "unspecified" may still be READ (EvaluationResultManifest.load()) --
# only NEW finalization calls are gated.


def _candidate_config(**overrides):
    defaults = dict(
        candidate="test-candidate", upstream_model="test/model", artifact_repo="test/model",
        exact_revision="a" * 40, tokenizer_revision="a" * 40, backend="dry-run",
        quantization="none", inference_config={"temperature": 0.0}, seed=42,
        context_window_used=1024, system_instruction="test instruction", hardware={"gpu": "none"},
    )
    defaults.update(overrides)
    return CandidateConfig(**defaults)


def _real_pipeline_result(tasks, *, run_id, suite_id="genesis-eval-test", suite_version="v1", config=None):
    """Runs the REAL production pipeline end to end (Phase 21B.4.8.2/.3):
    run_remote_generation_phase -> materialize_generation_artifact ->
    write_sealed_generation_artifact -> read back -> load_and_verify ->
    score_verified_generation_artifact -- using DryRunAdapter (a
    clearly-labeled non-real model) so these tests exercise the ACTUAL
    provenance-stamping code path, not a hand-built approximation of it."""
    task_ids, content_digest, scoring_digest = compute_suite_digests(tasks)
    config = config or _candidate_config()
    remote_records = run_remote_generation_phase(DryRunAdapter(), config, tasks)
    manifest = materialize_generation_artifact(
        remote_records, config, tasks, suite_id=suite_id, suite_version=suite_version,
        content_digest=content_digest, scoring_digest=scoring_digest, run_id=run_id,
        created_at="2026-09-19T00:00:00Z",
    )
    write_sealed_generation_artifact(manifest)
    serialized, expected_digest = read_sealed_generation_artifact(run_id)
    verified = load_and_verify_generation_artifact(serialized, expected_digest)
    return score_verified_generation_artifact(
        verified, config, tasks, suite_id=suite_id, suite_version=suite_version,
        content_digest=content_digest, scoring_digest=scoring_digest, started_at="2026-09-19T00:00:00Z",
    )


# Attacks 1-3: non-real provenance_kind values can never finalize.


def test_attack_1_unspecified_provenance_cannot_finalize_baseline():
    tasks = _tiny_task_set()
    result, scored_ids = _make_result(tasks, run_id="run-unspecified-provenance")
    result.provenance_kind = "unspecified"
    result.generation_artifact_digest = None
    result.generation_artifact_schema_version = None
    with pytest.raises(MissingGenerationProvenanceError, match="unspecified"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")
    with pytest.raises(FileNotFoundError):
        EvaluationSuiteManifest.load("genesis-eval-test", "v1")


def test_attack_2_synthetic_test_provenance_cannot_finalize_baseline():
    tasks = _tiny_task_set()
    result, scored_ids = _make_result(tasks, run_id="run-synthetic-provenance")
    result.provenance_kind = "synthetic_test"
    with pytest.raises(MissingGenerationProvenanceError, match="synthetic_test"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")


def test_attack_3_unknown_provenance_kind_cannot_finalize():
    tasks = _tiny_task_set()
    result, scored_ids = _make_result(tasks, run_id="run-unknown-provenance")
    result.provenance_kind = "totally-made-up-kind"
    with pytest.raises(MissingGenerationProvenanceError, match="totally-made-up-kind"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")


# Attacks 4-6: a real-declared result still needs genuine evidence.


def test_attack_4_real_provenance_with_missing_digest_fails():
    tasks = _tiny_task_set()
    result, scored_ids = _make_result(tasks, run_id="run-missing-digest")
    result.generation_artifact_digest = None
    with pytest.raises(GenerationArtifactMismatchError, match="well-formed"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")


def test_attack_5_real_provenance_with_malformed_digest_fails():
    tasks = _tiny_task_set()
    result, scored_ids = _make_result(tasks, run_id="run-malformed-digest")
    result.generation_artifact_digest = "not-a-valid-hex-digest"
    with pytest.raises(GenerationArtifactMismatchError, match="well-formed"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")


def test_attack_6_real_provenance_with_arbitrary_valid_looking_digest_fails():
    """A syntactically valid 64-hex digest that corresponds to NO real
    sealed artifact for this run_id must still be rejected."""
    tasks = _tiny_task_set()
    result, scored_ids = _make_result(tasks, run_id="run-no-such-run-id-xyz", complete=False)
    result.completed_at = "2026-09-18T00:00:00Z"
    scored_task_ids = [t.task_id for t in tasks if t.scoring_type != "llm_judge"]
    result.per_task_results = [{"task_id": tid, "passed": True} for tid in scored_task_ids]
    result.per_task_results += [{"task_id": t.task_id, "passed": None, "note": "UNSCORED_REQUIRES_JUDGE"}
                                 for t in tasks if t.scoring_type == "llm_judge"]
    result.provenance_kind = "real_generation_artifact"
    result.generation_artifact_digest = "a" * 64
    result.generation_artifact_schema_version = GENERATION_ARTIFACT_SCHEMA_VERSION
    with pytest.raises(GenerationArtifactMissingError):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_task_ids, suite_id="genesis-eval-test")


# Attack 7: a digest belonging to a DIFFERENT run's sealed artifact.


def test_attack_7_digest_for_another_run_fails():
    tasks = _tiny_task_set()
    other_result, other_scored_ids = _real_pipeline_result(tasks, run_id="run-other-real")
    other_result.finalized = True
    other_result.save()

    result, scored_ids = _make_result(tasks, run_id="run-claims-other-digest")
    result.generation_artifact_digest = other_result.generation_artifact_digest
    with pytest.raises(GenerationArtifactMismatchError, match="does not match"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")


# Attacks 8-12: the re-verified sealed artifact's identity disagrees
# with the result being finalized.


def _reseal_with_identity_change(result: EvaluationResultManifest, **field_overrides):
    """Re-seals a DIFFERENT, internally self-consistent manifest UNDER
    THE SAME on-disk path as `result.run_id` (never using
    write_sealed_generation_artifact()'s own filename-from-manifest.run_id
    behavior, since some of these attacks deliberately change the
    manifest's OWN run_id field) and updates `result.generation_artifact_
    digest` to the new artifact's digest -- simulating an attacker (or a
    bug) that swaps the sealed artifact and updates the digest reference
    but leaves the rest of `result`'s own recorded identity fields
    unchanged. The identity cross-check (baseline re-verification step
    5) must still catch the disagreement between the swapped artifact
    and everything else `result` claims about itself."""
    from dataclasses import replace as _replace

    from orca.eval.generation_artifact import GENERATION_ARTIFACT_MANIFEST_DIR, seal_generation_artifact

    serialized, expected_digest = read_sealed_generation_artifact(result.run_id)
    manifest = load_and_verify_generation_artifact(serialized, expected_digest).manifest
    tampered = _replace(manifest, **field_overrides)
    new_serialized, new_digest = seal_generation_artifact(tampered)
    (GENERATION_ARTIFACT_MANIFEST_DIR / f"{result.run_id}.json").write_bytes(new_serialized)
    (GENERATION_ARTIFACT_MANIFEST_DIR / f"{result.run_id}.sha256").write_bytes(new_digest.encode("ascii"))
    result.generation_artifact_digest = new_digest


def test_attack_8_artifact_run_id_mismatch_fails():
    tasks = _tiny_task_set()
    result, scored_ids = _real_pipeline_result(tasks, run_id="run-id-mismatch")
    _reseal_with_identity_change(result, run_id="a-different-run-id")
    with pytest.raises(GenerationArtifactMismatchError, match="run_id"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")


def test_attack_9_artifact_candidate_mismatch_fails():
    tasks = _tiny_task_set()
    result, scored_ids = _real_pipeline_result(tasks, run_id="run-candidate-mismatch")
    _reseal_with_identity_change(result, candidate="a-different-candidate")
    with pytest.raises(GenerationArtifactMismatchError, match="candidate"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")


def test_attack_10_artifact_revision_mismatch_fails():
    tasks = _tiny_task_set()
    result, scored_ids = _real_pipeline_result(tasks, run_id="run-revision-mismatch")
    _reseal_with_identity_change(result, exact_revision="b" * 40)
    with pytest.raises(GenerationArtifactMismatchError, match="exact_revision"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")


def test_attack_11_artifact_suite_mismatch_fails():
    tasks = _tiny_task_set()
    result, scored_ids = _real_pipeline_result(tasks, run_id="run-suite-mismatch")
    _reseal_with_identity_change(result, suite_id="a-different-suite")
    with pytest.raises(GenerationArtifactMismatchError, match="suite_id"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")


def test_attack_12_artifact_schema_mismatch_fails():
    tasks = _tiny_task_set()
    result, scored_ids = _real_pipeline_result(tasks, run_id="run-schema-mismatch")
    result.generation_artifact_schema_version = "some-other-schema-v99"
    with pytest.raises(GenerationArtifactMismatchError, match="schema"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")


# Attacks 13-14: sealed bundle / sidecar tamper detection.


def test_attack_13_artifact_json_tampered_after_seal_fails():
    tasks = _tiny_task_set()
    result, scored_ids = _real_pipeline_result(tasks, run_id="run-json-tampered")

    from orca.eval.generation_artifact import GENERATION_ARTIFACT_MANIFEST_DIR

    json_path = GENERATION_ARTIFACT_MANIFEST_DIR / "run-json-tampered.json"
    original = json_path.read_bytes()
    json_path.write_bytes(original.replace(b'"backend":"dry-run"', b'"backend":"tampered!"'))

    with pytest.raises(GenerationArtifactMismatchError, match="TOCTOU|re-verification"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")


def test_attack_14_sidecar_expected_digest_mismatch_fails():
    tasks = _tiny_task_set()
    result, scored_ids = _real_pipeline_result(tasks, run_id="run-sidecar-tampered")

    from orca.eval.generation_artifact import GENERATION_ARTIFACT_MANIFEST_DIR

    digest_path = GENERATION_ARTIFACT_MANIFEST_DIR / "run-sidecar-tampered.sha256"
    digest_path.write_bytes(b"0" * 64)

    with pytest.raises(GenerationArtifactMismatchError, match="does not match"):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")


# Attack 15: raw-response corruption still fails, at SCORING time --
# proving the earlier chain-of-custody link (Phase 21B.4.8.1/.2) still
# holds after this phase's refactor of the scoring entry points.


def test_attack_15_raw_response_corruption_still_fails_at_scoring_time():
    from pathlib import Path

    from orca.eval.generation_artifact import GenerationArtifactIntegrityError

    tasks = _tiny_task_set()
    config = _candidate_config()
    task_ids, content_digest, scoring_digest = compute_suite_digests(tasks)
    remote_records = run_remote_generation_phase(DryRunAdapter(), config, tasks)
    manifest = materialize_generation_artifact(
        remote_records, config, tasks, suite_id="genesis-eval-test", suite_version="v1",
        content_digest=content_digest, scoring_digest=scoring_digest, run_id="run-raw-corrupted",
        created_at="2026-09-19T00:00:00Z",
    )
    corrupted_ref = next(r["raw_response_ref"] for r in manifest.records if r["raw_response_ref"])
    Path(corrupted_ref).write_bytes(b"CORRUPTED, DOES NOT MATCH THE RECORDED HASH")
    write_sealed_generation_artifact(manifest)
    serialized, expected_digest = read_sealed_generation_artifact("run-raw-corrupted")
    verified = load_and_verify_generation_artifact(serialized, expected_digest)
    with pytest.raises(GenerationArtifactIntegrityError, match="does not match"):
        score_verified_generation_artifact(
            verified, config, tasks, suite_id="genesis-eval-test", suite_version="v1",
            content_digest=content_digest, scoring_digest=scoring_digest, started_at="2026-09-19T00:00:00Z",
        )


# Attack 16: the real scoring entry point refuses a bare manifest.


def test_attack_16_raw_manifest_rejected_by_real_scoring_entry_point():
    tasks = _tiny_task_set()
    config = _candidate_config()
    task_ids, content_digest, scoring_digest = compute_suite_digests(tasks)
    remote_records = run_remote_generation_phase(DryRunAdapter(), config, tasks)
    manifest = materialize_generation_artifact(
        remote_records, config, tasks, suite_id="genesis-eval-test", suite_version="v1",
        content_digest=content_digest, scoring_digest=scoring_digest, run_id="run-bare-manifest",
        created_at="2026-09-19T00:00:00Z",
    )
    with pytest.raises(TypeError, match="VerifiedGenerationArtifact"):
        score_verified_generation_artifact(
            manifest, config, tasks, suite_id="genesis-eval-test", suite_version="v1",
            content_digest=content_digest, scoring_digest=scoring_digest, started_at="2026-09-19T00:00:00Z",
        )


# Attacks 17-19: verified-artifact scoring automatically stamps provenance.


def test_attack_17_18_19_verified_scoring_automatically_stamps_provenance():
    tasks = _tiny_task_set()
    result, scored_ids = _real_pipeline_result(tasks, run_id="run-auto-stamped")
    assert result.provenance_kind == "real_generation_artifact"  # 17
    assert result.generation_artifact_digest is not None and len(result.generation_artifact_digest) == 64  # 18
    assert result.generation_artifact_schema_version == GENERATION_ARTIFACT_SCHEMA_VERSION  # 19

    _serialized, expected_digest = read_sealed_generation_artifact("run-auto-stamped")
    assert result.generation_artifact_digest == expected_digest  # stamped digest is the EXACT verified one


# Attack 20: finalization succeeds end-to-end through the real pipeline,
# proving re-verification actually runs (not merely trusting a stamp).


def test_attack_20_finalized_baseline_re_verifies_stored_artifact_before_freeze():
    tasks = _tiny_task_set()
    result, scored_ids = _real_pipeline_result(tasks, run_id="run-full-pipeline-finalize")
    finalized = record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")
    assert finalized.finalized is True
    assert finalized.provenance_kind == "real_generation_artifact"
    suite = EvaluationSuiteManifest.load("genesis-eval-test", "v1")
    assert suite.frozen is True


# Attack 21: artifact removed after scoring but before finalization.


def test_attack_21_artifact_removed_after_scoring_causes_failure():
    tasks = _tiny_task_set()
    result, scored_ids = _real_pipeline_result(tasks, run_id="run-artifact-removed")

    from orca.eval.generation_artifact import GENERATION_ARTIFACT_MANIFEST_DIR

    (GENERATION_ARTIFACT_MANIFEST_DIR / "run-artifact-removed.json").unlink()
    (GENERATION_ARTIFACT_MANIFEST_DIR / "run-artifact-removed.sha256").unlink()

    with pytest.raises(GenerationArtifactMissingError):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")
    with pytest.raises(FileNotFoundError):
        EvaluationSuiteManifest.load("genesis-eval-test", "v1")


# Attack 22: artifact replaced (with another VALID but different sealed
# artifact) after scoring but before finalization.


def test_attack_22_artifact_replaced_after_scoring_causes_failure():
    tasks = _tiny_task_set()
    result, scored_ids = _real_pipeline_result(tasks, run_id="run-artifact-replaced")

    # Replace the sealed artifact with an entirely different (but
    # internally self-consistent) one for a different candidate,
    # re-sealed under the SAME run_id -- the digest changes, so
    # result.generation_artifact_digest (captured at scoring time) no
    # longer matches the sidecar's new expected digest.
    other_config = _candidate_config(candidate="replacement-candidate")
    task_ids, content_digest, scoring_digest = compute_suite_digests(tasks)
    remote_records = run_remote_generation_phase(DryRunAdapter(), other_config, tasks)
    replacement_manifest = materialize_generation_artifact(
        remote_records, other_config, tasks, suite_id="genesis-eval-test", suite_version="v1",
        content_digest=content_digest, scoring_digest=scoring_digest, run_id="run-artifact-replaced",
        created_at="2026-09-19T00:00:01Z",
    )
    write_sealed_generation_artifact(replacement_manifest)

    with pytest.raises(GenerationArtifactMismatchError):
        record_baseline_and_freeze_suite(tasks=tasks, result=result, scored_task_ids=scored_ids, suite_id="genesis-eval-test")


# Attack 23: DryRunAdapter (via run_suite()) can never freeze the suite.


def test_attack_23_dry_run_adapter_cannot_freeze_suite():
    """run_suite() (which load_and_verify_suite()s against the CURRENT
    in-code task list, i.e. the real genesis-eval-v1 90-task suite --
    not the tiny fixture suite used elsewhere in this file) must never
    let a DryRunAdapter result freeze the real suite."""
    real_tasks = all_tasks()
    task_ids, content_digest, scoring_digest = compute_suite_digests(real_tasks)
    manifest = EvaluationSuiteManifest(
        suite_id="genesis-eval-dryrun-test", version="v1", task_ids=task_ids,
        content_digest=content_digest, scoring_contract_digest=scoring_digest, creation_code_sha="sha",
    )
    manifest.save()

    config = _candidate_config()
    result, scored_task_ids = run_suite(DryRunAdapter(), config, suite_id="genesis-eval-dryrun-test", suite_version="v1", run_id="run-dryrun-attempt")
    assert result.provenance_kind == "synthetic_test"

    with pytest.raises(MissingGenerationProvenanceError, match="synthetic_test"):
        record_baseline_and_freeze_suite(tasks=real_tasks, result=result, scored_task_ids=scored_task_ids, suite_id="genesis-eval-dryrun-test")

    reloaded = EvaluationSuiteManifest.load("genesis-eval-dryrun-test", "v1")
    assert reloaded.frozen is False


# Attack 24: legacy unspecified manifests remain READABLE, just never
# newly finalizable.


def test_attack_24_legacy_unspecified_manifest_still_readable_but_not_finalizable():
    tasks = _tiny_task_set()
    result, scored_ids = _make_result(tasks, run_id="run-legacy-unspecified")
    result.provenance_kind = "unspecified"
    result.generation_artifact_digest = None
    result.generation_artifact_schema_version = None
    result.finalized = True  # simulate a manifest persisted before this phase's gate existed
    result.save()

    # READ compatibility: loading a legacy manifest must still work.
    reloaded = EvaluationResultManifest.load("run-legacy-unspecified")
    assert reloaded.provenance_kind == "unspecified"
    assert reloaded.finalized is True

    # But it can never be used to freeze a (different, still-unfrozen) suite.
    fresh_result, fresh_scored_ids = _make_result(tasks, run_id="run-legacy-unspecified-2", suite_id="genesis-eval-legacy-test")
    fresh_result.provenance_kind = "unspecified"
    fresh_result.generation_artifact_digest = None
    fresh_result.generation_artifact_schema_version = None
    with pytest.raises(MissingGenerationProvenanceError):
        record_baseline_and_freeze_suite(tasks=tasks, result=fresh_result, scored_task_ids=fresh_scored_ids, suite_id="genesis-eval-legacy-test")
    with pytest.raises(FileNotFoundError):
        EvaluationSuiteManifest.load("genesis-eval-legacy-test", "v1")
