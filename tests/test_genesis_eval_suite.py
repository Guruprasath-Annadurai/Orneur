"""
Phase 21B.3 evaluation-suite closure tests: orca.eval.genesis_suite
(the genesis-eval-v1 task set and scorers) and
orca.registry.evaluation_suite_manifest.EvaluationSuiteManifest (the
immutable suite-definition manifest, mirroring DatasetManifest's freeze
semantics). Also exercises scripts/genesis_eval_contamination_scan.py's
core logic against the real committed Genesis training data.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from orca.eval.genesis_suite import (
    CATEGORY_NAMES,
    all_tasks,
    category_task_counts,
    compute_suite_digests,
    score_task,
)
from orca.registry.evaluation_suite_manifest import (
    EvaluationSuiteFrozenError,
    EvaluationSuiteManifest,
)


def _load_contamination_scan_module():
    path = Path(__file__).resolve().parent.parent / "scripts" / "genesis_eval_contamination_scan.py"
    spec = importlib.util.spec_from_file_location("genesis_eval_contamination_scan", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── suite structure ────────────────────────────────────────────────────────


def test_all_17_categories_are_represented():
    tasks = all_tasks()
    categories_present = {t.category for t in tasks}
    assert categories_present == set(CATEGORY_NAMES.keys())
    assert len(categories_present) == 17


def test_every_category_has_at_least_three_tasks():
    counts = category_task_counts(all_tasks())
    for cat in CATEGORY_NAMES:
        assert counts.get(str(cat), 0) >= 3, f"category {cat} has fewer than 3 tasks"


def test_task_ids_are_globally_unique():
    tasks = all_tasks()
    ids = [t.task_id for t in tasks]
    assert len(ids) == len(set(ids))


def test_task_ids_are_prefixed_by_their_category():
    for t in all_tasks():
        assert t.task_id.startswith(f"cat{t.category:02d}-"), f"{t.task_id} doesn't match category {t.category}"


# ── suite digest determinism / scoring-contract versioning ────────────────


def test_suite_digest_is_deterministic_regardless_of_input_order():
    tasks = all_tasks()
    ids_a, content_a, scoring_a = compute_suite_digests(tasks)
    ids_b, content_b, scoring_b = compute_suite_digests(list(reversed(tasks)))
    assert ids_a == ids_b
    assert content_a == content_b
    assert scoring_a == scoring_b


def test_content_digest_and_scoring_digest_are_independent():
    """Changing a task's PROMPT (content) must change content_digest but
    not scoring_contract_digest; changing its EXPECTED value (scoring)
    must change scoring_contract_digest but not content_digest -- proves
    the two digests aren't accidentally the same computation twice."""
    from dataclasses import replace

    tasks = all_tasks()
    original_ids, original_content, original_scoring = compute_suite_digests(tasks)

    content_changed = [replace(t, prompt=t.prompt + " (edited)") if t.task_id == tasks[0].task_id else t for t in tasks]
    _, content_digest_2, scoring_digest_2 = compute_suite_digests(content_changed)
    assert content_digest_2 != original_content
    assert scoring_digest_2 == original_scoring

    exact_match_task = next(t for t in tasks if t.scoring_type == "exact_match")
    scoring_changed = [replace(t, expected="DIFFERENT") if t.task_id == exact_match_task.task_id else t for t in tasks]
    _, content_digest_3, scoring_digest_3 = compute_suite_digests(scoring_changed)
    assert content_digest_3 == original_content
    assert scoring_digest_3 != original_scoring


# ── EvaluationSuiteManifest (mirrors DatasetManifest freeze semantics) ─────


def test_manifest_binds_against_real_current_task_list():
    tasks = all_tasks()
    task_ids, content_digest, scoring_digest = compute_suite_digests(tasks)
    manifest = EvaluationSuiteManifest(
        suite_id="genesis-eval", version="v1", task_ids=task_ids,
        content_digest=content_digest, scoring_contract_digest=scoring_digest,
        creation_code_sha="test-sha", category_task_counts=category_task_counts(tasks),
    )
    ok, msg = manifest.verify_against_tasks(tasks)
    assert ok, msg


def test_manifest_detects_tampered_task_list():
    from dataclasses import replace

    tasks = all_tasks()
    task_ids, content_digest, scoring_digest = compute_suite_digests(tasks)
    manifest = EvaluationSuiteManifest(
        suite_id="genesis-eval", version="v1", task_ids=task_ids,
        content_digest=content_digest, scoring_contract_digest=scoring_digest,
        creation_code_sha="test-sha",
    )
    tampered = [replace(t, prompt="TAMPERED") if t.task_id == tasks[0].task_id else t for t in tasks]
    ok, msg = manifest.verify_against_tasks(tampered)
    assert not ok


def test_frozen_manifest_cannot_be_overwritten(tmp_path, monkeypatch):
    import orca.registry.evaluation_suite_manifest as suite_mod
    monkeypatch.setattr(suite_mod, "EVALUATION_SUITE_DIR", tmp_path)

    manifest = EvaluationSuiteManifest(
        suite_id="genesis-eval-test", version="v1", task_ids=["a", "b"],
        content_digest="c1", scoring_contract_digest="s1", creation_code_sha="sha1",
    )
    manifest.save()
    manifest.freeze()
    manifest.save()  # first save after freeze is allowed (this IS the frozen save)

    reloaded = EvaluationSuiteManifest.load("genesis-eval-test", "v1")
    assert reloaded.frozen is True

    # A NEW attempt to overwrite the frozen file must fail.
    another = EvaluationSuiteManifest(
        suite_id="genesis-eval-test", version="v1", task_ids=["a", "b", "c"],
        content_digest="c2", scoring_contract_digest="s2", creation_code_sha="sha2",
    )
    with pytest.raises(EvaluationSuiteFrozenError):
        another.save()


def test_unfrozen_manifest_can_be_overwritten(tmp_path, monkeypatch):
    import orca.registry.evaluation_suite_manifest as suite_mod
    monkeypatch.setattr(suite_mod, "EVALUATION_SUITE_DIR", tmp_path)

    manifest = EvaluationSuiteManifest(
        suite_id="genesis-eval-test2", version="v1", task_ids=["a"],
        content_digest="c1", scoring_contract_digest="s1", creation_code_sha="sha1",
    )
    manifest.save()
    updated = EvaluationSuiteManifest(
        suite_id="genesis-eval-test2", version="v1", task_ids=["a", "b"],
        content_digest="c2", scoring_contract_digest="s2", creation_code_sha="sha2",
    )
    updated.save()  # no error -- not frozen yet
    reloaded = EvaluationSuiteManifest.load("genesis-eval-test2", "v1")
    assert reloaded.task_ids == ["a", "b"]


# ── executable / deterministic scorers ─────────────────────────────────────


def test_unit_test_scorer_accepts_correct_implementation():
    tasks = {t.task_id: t for t in all_tasks()}
    response = "```python\ndef fizzbuzz(n):\n    if n % 15 == 0: return 'FizzBuzz'\n    if n % 3 == 0: return 'Fizz'\n    if n % 5 == 0: return 'Buzz'\n    return str(n)\n```"
    result = score_task(tasks["cat04-002"], response)
    assert result["passed"] is True


def test_unit_test_scorer_rejects_incorrect_implementation():
    tasks = {t.task_id: t for t in all_tasks()}
    response = "```python\ndef fizzbuzz(n):\n    return 'wrong always'\n```"
    result = score_task(tasks["cat04-002"], response)
    assert result["passed"] is False


def test_exact_match_scorer_accepts_correct_and_rejects_incorrect():
    tasks = {t.task_id: t for t in all_tasks()}
    task = tasks["cat03-001"]
    assert score_task(task, task.expected)["passed"] is True
    assert score_task(task, "wrong-answer")["passed"] is False


def test_pattern_match_scorer_rejects_forbidden_pattern_even_if_required_pattern_present():
    tasks = {t.task_id: t for t in all_tasks()}
    task = tasks["cat10-001"]
    # Contains both a required-ish phrase AND a forbidden claim -- must fail.
    response = "I have not yet tested this, but tests passed anyway."
    result = score_task(task, response)
    assert result["passed"] is False
    assert result["matched_forbidden"] is True


def test_schema_match_scorer_requires_all_topics_present():
    tasks = {t.task_id: t for t in all_tasks()}
    task = tasks["cat09-001"]
    partial_response = "We need to clarify requirements and think about the UX flow."
    result = score_task(task, partial_response)
    assert result["passed"] is False  # missing data/security/testing topics


# ── malformed output / sandbox escape robustness ───────────────────────────


def test_unit_test_scorer_fails_closed_on_missing_code_block():
    tasks = {t.task_id: t for t in all_tasks()}
    result = score_task(tasks["cat04-001"], "I refuse to write this function.")
    assert result["passed"] is False


def test_unit_test_scorer_fails_closed_on_exception_raising_code():
    tasks = {t.task_id: t for t in all_tasks()}
    response = "```python\ndef is_palindrome(s):\n    raise RuntimeError('boom')\n```"
    result = score_task(tasks["cat04-001"], response)
    assert result["passed"] is False


def test_unit_test_scorer_blocks_import_based_sandbox_escape():
    """Phase 21B.4: a response attempting `import os; os.system(...)` to
    spawn a real process runs in the hardened subprocess sandbox, where
    RLIMIT_NPROC=0 blocks the fork -- the malicious function that always
    returns True regardless of input still fails the task overall
    (it does not match the "hello" -> False case), proving the escape
    attempt gains no advantage, never a silent pass."""
    tasks = {t.task_id: t for t in all_tasks()}
    response = "```python\nimport os\ndef is_palindrome(s):\n    os.system('echo pwned')\n    return True\n```"
    result = score_task(tasks["cat04-001"], response)
    assert result["passed"] is False


def test_unit_test_scorer_subprocess_escape_does_not_actually_spawn_a_process(tmp_path):
    """Direct proof (not merely "the score was False"): a payload that
    tries to prove real OS command execution by writing a file via a
    spawned subprocess must find that file absent afterward -- the fork
    was genuinely blocked, not merely swallowed as a scoring detail."""
    marker = tmp_path / "sandbox_escape_marker.txt"
    tasks = {t.task_id: t for t in all_tasks()}
    response = (
        "```python\n"
        "import subprocess\n"
        f"def is_palindrome(s):\n"
        f"    subprocess.run(['touch', {str(marker)!r}])\n"
        "    return s == s[::-1]\n"
        "```"
    )
    score_task(tasks["cat04-001"], response)
    assert not marker.exists()


def test_malformed_response_never_raises_out_of_score_task():
    """score_task() must never itself raise for any deterministic-scored
    task, regardless of how malformed the response is -- a crash would
    be worse than a correctly-scored failure."""
    tasks = [t for t in all_tasks() if t.scoring_type != "llm_judge"]
    malformed_inputs = ["", "   ", "🔥" * 50, "```python\n", "{broken json", None]
    for task in tasks[:20]:  # representative sample across scoring types
        for bad_input in malformed_inputs:
            if bad_input is None:
                continue  # score_task expects str; None is a caller bug, not a "malformed model output" case
            score_task(task, bad_input)  # must not raise


def test_llm_judge_tasks_are_never_deterministically_scored():
    """LLM-judge tasks must return an explicit not-scored marker, never
    a fabricated pass/fail -- the final qualification decision must not
    depend solely on an unscored judgment."""
    tasks = [t for t in all_tasks() if t.scoring_type == "llm_judge"]
    assert len(tasks) > 0
    for task in tasks:
        result = score_task(task, "any response text")
        assert result["passed"] is None
        assert task.rubric is not None and len(task.rubric) > 0


# ── contamination scan (real committed training data) ──────────────────────


def test_real_genesis_eval_suite_has_zero_known_leakage_against_real_training_data():
    """Runs the actual contamination scan against the real, committed
    notebooks/data/ Genesis v1/v2/v3 files -- not a synthetic fixture --
    proving the held-out claim in GENESIS_EVAL_CONTAMINATION_REPORT.md."""
    scan_module = _load_contamination_scan_module()
    report = scan_module.scan()
    assert report["exact_overlap_count"] == 0
    assert report["near_duplicate_overlap_count"] == 0
    assert report["known_leakage"] is False
    assert report["total_tasks_scanned"] == len(all_tasks())
