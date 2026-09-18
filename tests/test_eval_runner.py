"""
Phase 21B.4 (§3) evaluation-runner plumbing tests. Uses
orca.eval.runner.DryRunAdapter -- explicitly NOT a real model -- to
validate the runner's own mechanics (denominator integrity, failure
capture, digest wiring, exact-revision pinning enforcement) without any
real inference. No test in this file may be read as evidence of a real
candidate baseline.
"""
from __future__ import annotations

import pytest

from orca.eval.genesis_suite import all_tasks, category_task_counts, compute_suite_digests
from orca.eval.runner import (
    CandidateConfig,
    DryRunAdapter,
    GenerationRecord,
    GenerationResult,
    load_and_verify_suite,
    run_generation_phase,
    run_scoring_phase,
    run_suite,
)
from orca.registry.evaluation_suite_manifest import EvaluationSuiteManifest


def _register_real_suite_manifest():
    tasks = all_tasks()
    task_ids, content_digest, scoring_digest = compute_suite_digests(tasks)
    manifest = EvaluationSuiteManifest(
        suite_id="genesis-eval", version="v1", task_ids=task_ids,
        content_digest=content_digest, scoring_contract_digest=scoring_digest,
        creation_code_sha="test-sha", category_task_counts=category_task_counts(tasks),
    )
    manifest.save()
    return manifest


def _valid_candidate_config(**overrides) -> CandidateConfig:
    defaults = dict(
        candidate="dry-run-validation-candidate",
        upstream_model="test/upstream-model",
        artifact_repo="test/artifact-repo",
        exact_revision="a" * 40,
        tokenizer_revision="a" * 40,
        backend="dry-run",
        quantization="none",
        inference_config={"temperature": 0.0, "top_p": 1.0, "max_new_tokens": 64},
        seed=42,
        context_window_used=2048,
        system_instruction="You are a test system instruction.",
        hardware={"gpu": "none (dry run)"},
    )
    defaults.update(overrides)
    return CandidateConfig(**defaults)


# ── revision pinning enforcement ────────────────────────────────────────


def test_candidate_config_rejects_unpinned_revision():
    with pytest.raises(ValueError, match="exact pinned revision"):
        _valid_candidate_config(exact_revision="main")


def test_candidate_config_rejects_empty_revision():
    with pytest.raises(ValueError, match="exact pinned revision"):
        _valid_candidate_config(exact_revision="")


def test_candidate_config_accepts_a_real_looking_sha():
    cfg = _valid_candidate_config(exact_revision="946bc9ac74a6c1f8cf012497c503a119b2fcf2eb")
    assert cfg.exact_revision == "946bc9ac74a6c1f8cf012497c503a119b2fcf2eb"


# ── load_and_verify_suite ──────────────────────────────────────────────


def test_load_and_verify_suite_fails_if_never_registered():
    with pytest.raises(FileNotFoundError):
        load_and_verify_suite("genesis-eval", "v1")


def test_load_and_verify_suite_succeeds_against_a_real_registered_manifest():
    _register_real_suite_manifest()
    tasks, manifest = load_and_verify_suite("genesis-eval", "v1")
    assert len(tasks) == len(manifest.task_ids)


# ── run_suite plumbing (DryRunAdapter -- never a real model) ──────────────


def test_run_suite_denominator_integrity_every_task_accounted_for():
    _register_real_suite_manifest()
    tasks = all_tasks()
    adapter = DryRunAdapter()
    result, scored_task_ids = run_suite(adapter, _valid_candidate_config())

    accounted = {e["task_id"] for e in result.per_task_results} | {e["task_id"] for e in result.generation_failures}
    assert accounted == {t.task_id for t in tasks}


def test_run_suite_separates_deterministic_from_llm_judge_unscored():
    _register_real_suite_manifest()
    adapter = DryRunAdapter()
    result, scored_task_ids = run_suite(adapter, _valid_candidate_config())

    llm_judge_tasks = [t for t in all_tasks() if t.scoring_type == "llm_judge"]
    for t in llm_judge_tasks:
        entry = next(e for e in result.per_task_results if e["task_id"] == t.task_id)
        assert entry["passed"] is None
        assert entry["note"] == "UNSCORED_REQUIRES_JUDGE"
    assert set(str(t.category) for t in llm_judge_tasks) <= set(result.unscored_categories)


def test_run_suite_captures_generation_failures_without_dropping_them():
    _register_real_suite_manifest()

    class _AlwaysFailsAdapter:
        def generate(self, prompt, *, system_instruction, config):
            return GenerationResult(text=None, latency_ms=1.0, error="simulated backend timeout")

    result, scored_task_ids = run_suite(_AlwaysFailsAdapter(), _valid_candidate_config())
    tasks = all_tasks()
    assert len(result.generation_failures) == len(tasks)
    assert result.per_task_results == []
    assert all(f["reason"] == "simulated backend timeout" for f in result.generation_failures)


def test_run_suite_records_suite_digests_matching_the_persisted_manifest():
    manifest = _register_real_suite_manifest()
    result, _ = run_suite(DryRunAdapter(), _valid_candidate_config())
    assert result.suite_content_digest == manifest.content_digest
    assert result.suite_scoring_contract_digest == manifest.scoring_contract_digest


def test_run_suite_deterministic_summary_reflects_actual_pass_rate():
    _register_real_suite_manifest()
    result, _ = run_suite(DryRunAdapter(), _valid_candidate_config())
    total = result.deterministic_summary["total"]
    passed = result.deterministic_summary["passed"]
    assert total > 0
    assert 0 <= passed <= total
    # A fixed placeholder response predictably fails exact_match/unit_test
    # tasks and predictably matches some pattern-match "forbidden" claims
    # -- confirms the dry-run adapter is not somehow rigged to always pass.
    assert passed < total


def test_run_suite_persists_raw_responses_by_reference_not_inline():
    _register_real_suite_manifest()
    result, _ = run_suite(DryRunAdapter(), _valid_candidate_config())
    from pathlib import Path

    scored_entries = [e for e in result.per_task_results if e.get("raw_response_ref")]
    assert scored_entries
    for e in scored_entries[:3]:
        assert Path(e["raw_response_ref"]).exists()
        assert "DRY_RUN_PLACEHOLDER" in Path(e["raw_response_ref"]).read_text()


# ── Phase 21B.4.8: GenerationExecutor / ScoringExecutor split ────────────


def test_run_generation_phase_never_calls_score_task(monkeypatch):
    """The whole point of the split: a trusted-inference-only worker
    (e.g. a Modal GPU machine with no SandboxBackend available) must be
    able to run generation without genesis_suite.score_task ever being
    imported or invoked -- monkeypatch it to raise, and generation must
    still succeed untouched."""
    import orca.eval.genesis_suite as genesis_suite_mod

    def _boom(*a, **k):
        raise AssertionError("score_task must never be called during generation phase")

    monkeypatch.setattr(genesis_suite_mod, "score_task", _boom)

    _register_real_suite_manifest()
    tasks, _ = load_and_verify_suite()
    records = run_generation_phase(DryRunAdapter(), _valid_candidate_config(), tasks, run_id="test-gen-only")

    assert len(records) == len(tasks)
    assert all(isinstance(r, GenerationRecord) for r in records)
    assert any(r.text is not None for r in records)


def test_run_scoring_phase_works_from_manually_built_generation_records():
    """No adapter, no GPU, nothing GPU-related involved at all -- proves
    the ScoringExecutor half is independently usable given only
    GenerationRecords, e.g. ones deserialized from a file a separate
    trusted-inference worker produced."""
    _register_real_suite_manifest()
    tasks, _ = load_and_verify_suite()
    task_ids, content_digest, scoring_digest = compute_suite_digests(tasks)

    records = [
        GenerationRecord(
            task_id=t.task_id, category=t.category, scoring_type=t.scoring_type,
            text="[DRY_RUN_PLACEHOLDER_RESPONSE -- NOT A REAL MODEL OUTPUT]", error=None,
            latency_ms=1.0, raw_response_ref=None,
        )
        for t in tasks
    ]

    result, scored_task_ids = run_scoring_phase(
        records, _valid_candidate_config(), tasks,
        suite_id="genesis-eval", suite_version="v1",
        content_digest=content_digest, scoring_digest=scoring_digest,
        run_id="test-scoring-only", started_at="2026-01-01T00:00:00Z",
    )
    assert len(result.per_task_results) + len(result.generation_failures) == len(tasks)
    assert scored_task_ids


def test_split_phases_composed_separately_match_run_suite_directly():
    """run_generation_phase() + run_scoring_phase(), called as two
    separate steps (simulating a GPU worker producing records, then a
    Docker-equipped worker scoring them later), must produce the same
    EvaluationResultManifest content as calling run_suite() directly
    with the same adapter/config/run_id -- proving the split is a true
    decomposition, not a behavior change."""
    _register_real_suite_manifest()
    config = _valid_candidate_config()

    direct_result, direct_scored_ids = run_suite(DryRunAdapter(), config, run_id="test-direct")

    tasks, _ = load_and_verify_suite()
    task_ids, content_digest, scoring_digest = compute_suite_digests(tasks)
    records = run_generation_phase(DryRunAdapter(), config, tasks, run_id="test-split")
    split_result, split_scored_ids = run_scoring_phase(
        records, config, tasks,
        suite_id="genesis-eval", suite_version="v1",
        content_digest=content_digest, scoring_digest=scoring_digest,
        run_id="test-split", started_at="2026-01-01T00:00:00Z",
    )

    assert split_scored_ids == direct_scored_ids
    assert split_result.deterministic_summary == direct_result.deterministic_summary
    assert split_result.per_category_summary == direct_result.per_category_summary
    assert split_result.unscored_categories == direct_result.unscored_categories
    assert len(split_result.per_task_results) == len(direct_result.per_task_results)
