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
    IncompleteResultError,
    record_baseline_and_freeze_suite,
)
from orca.eval.genesis_suite import EvalTask, all_tasks, compute_suite_digests
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


def _make_result(tasks: list[EvalTask], *, run_id: str, complete: bool = True) -> tuple[EvaluationResultManifest, list[str]]:
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
        run_id=run_id, candidate="test-candidate", upstream_model="test/model",
        artifact_repo="test/model", exact_revision="abc123", tokenizer_revision="abc123",
        backend="test-backend", quantization="none", inference_config={"temperature": 0.0},
        seed=42, context_window_used=1024, system_instruction_digest="sha256:deadbeef",
        software_commit_sha="test-sha", hardware={"gpu": "none"},
        suite_id="genesis-eval-test", suite_version="v1",
        suite_content_digest=content_digest, suite_scoring_contract_digest=scoring_digest,
        per_task_results=per_task, unscored_categories=["2"],
        completed_at="2026-09-18T00:00:00Z" if complete else None,
    )
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
    result_a, scored_ids_a = _make_result(tasks, run_id="shared-run-id")
    result_a.candidate = "candidate-A"
    record_baseline_and_freeze_suite(tasks=tasks, result=result_a, scored_task_ids=scored_ids_a, suite_id="genesis-eval-test")

    result_b, scored_ids_b = _make_result(tasks, run_id="shared-run-id")
    result_b.candidate = "candidate-B"
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
            result, scored_ids = _make_result(tasks, run_id=run_id)
            result.suite_id = "genesis-eval-concurrency-test"
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
