"""
Genesis foundation-model evaluation runner (Phase 21B.4, §3).

Provider/model-neutral: any real inference backend plugs in by
implementing `ModelAdapter`. This module NEVER calls a real model
itself -- it drives whatever adapter it is given. `DryRunAdapter` (at
the bottom of this file) is provided ONLY to validate the runner's own
plumbing (denominator integrity, failure capture, digest wiring) in
tests, and is unmistakably documented and named as non-real -- it must
never be presented as, or mistaken for, a real model evaluation.

Design goals (spec §3): load genesis-eval-v1, verify the persisted
suite manifest and its content/scoring digests, execute every task,
preserve denominator integrity (no silent skips), capture malformed
responses and timeout/backend failures explicitly, capture latency and
raw-response references, capture scorer output, aggregate per-category
and deterministic totals, and separate deterministic scoring from
rubric/LLM-judge-required categories (never fabricating a score for the
latter -- see CANDIDATE_UNSCORED_MARKER).
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from orca.config import ORCA_HOME
from orca.eval.genesis_suite import EvalTask, all_tasks, compute_suite_digests, score_task
from orca.registry.evaluation_result_manifest import EvaluationResultManifest
from orca.registry.evaluation_suite_manifest import EvaluationSuiteManifest

CANDIDATE_UNSCORED_MARKER = "UNSCORED_REQUIRES_JUDGE"

# Deliberately its OWN module-level constant (not derived from another
# module's constant, e.g. `evaluation_result_manifest.EVALUATION_RESULT_DIR
# .parent / ...`) -- a derived constant would be computed once at import
# time from the OTHER module's un-monkeypatched value, silently leaking
# real-path writes past test isolation even when that other constant is
# correctly monkeypatched later. See tests/conftest.py's autouse registry-
# isolation fixture, which patches this constant directly.
RAW_RESPONSE_DIR = ORCA_HOME / "registry" / "evaluation_raw_responses"
RAW_RESPONSE_DIR.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class GenerationResult:
    """What a ModelAdapter returns for one task."""
    text: str | None                 # None if generation failed
    latency_ms: float
    error: str | None = None         # set (text=None) on timeout/API/backend failure


class ModelAdapter(Protocol):
    """Implement this against a real inference backend (transformers,
    vLLM, an API) to actually run the shootout. The runner never
    constructs or assumes a specific backend."""

    def generate(self, prompt: str, *, system_instruction: str, config: dict) -> GenerationResult: ...


@dataclass(frozen=True)
class CandidateConfig:
    candidate: str
    upstream_model: str
    artifact_repo: str
    exact_revision: str
    tokenizer_revision: str | None
    backend: str
    quantization: str
    inference_config: dict
    seed: int | None
    context_window_used: int
    system_instruction: str
    hardware: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.exact_revision or self.exact_revision.strip().lower() in ("main", "latest", "head", ""):
            raise ValueError(
                f"CandidateConfig.exact_revision={self.exact_revision!r} is not an exact pinned revision -- "
                "no candidate may be evaluated without exact model revision pinning (spec §3)."
            )


def _sha256_of_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _current_git_sha() -> str:
    import subprocess

    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5,
        ).stdout.strip() or "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def _persist_raw_response(run_id: str, task_id: str, text: str | None) -> str | None:
    """Content-addressed raw-response storage, referenced from the
    result manifest by pointer rather than inlining every generation
    into the core manifest (spec §11: 'Raw generations should be
    persisted separately or by content-addressed reference')."""
    if text is None:
        return None
    digest = _sha256_of_text(text)[:16]
    run_dir = RAW_RESPONSE_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / f"{task_id}-{digest}.txt"
    path.write_text(text)
    return str(path)


def load_and_verify_suite(suite_id: str = "genesis-eval", suite_version: str = "v1") -> tuple[list[EvalTask], EvaluationSuiteManifest]:
    """Loads the CURRENT in-code task list, loads the PERSISTED suite
    manifest (raises FileNotFoundError if it has never been registered
    -- a candidate cannot be evaluated against a suite that was never
    persisted), and verifies the two agree before returning either.
    This is the "load persisted suite -> verify identity/version ->
    verify content_digest -> verify scoring_contract_digest" prefix of
    the required lifecycle."""
    tasks = all_tasks()
    suite_manifest = EvaluationSuiteManifest.load(suite_id, suite_version)
    ok, msg = suite_manifest.verify_against_tasks(tasks)
    if not ok:
        raise ValueError(f"Persisted suite {suite_id}-{suite_version} does not match the current task list: {msg}")
    return tasks, suite_manifest


def run_suite(
    adapter: ModelAdapter,
    candidate_config: CandidateConfig,
    *,
    suite_id: str = "genesis-eval",
    suite_version: str = "v1",
    run_id: str | None = None,
) -> tuple[EvaluationResultManifest, list[str]]:
    """Executes EVERY task in the persisted, verified suite against
    `adapter`, producing a NOT-yet-finalized EvaluationResultManifest
    (caller must pass this to
    orca.eval.baseline.record_baseline_and_freeze_suite() to finalize
    it). Returns (result, scored_task_ids) -- scored_task_ids excludes
    llm_judge tasks, matching record_baseline_and_freeze_suite()'s
    completeness-check contract.

    Denominator integrity: every task in the suite gets EITHER a
    per_task_results entry (deterministic categories) or an
    unscored_categories-tagged entry, OR a generation_failures entry (if
    generation itself failed) -- never silently dropped."""
    tasks, suite_manifest = load_and_verify_suite(suite_id, suite_version)
    task_ids, content_digest, scoring_digest = compute_suite_digests(tasks)

    resolved_run_id = run_id or f"run-{uuid.uuid4().hex[:16]}"
    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    per_task_results: list[dict] = []
    generation_failures: list[dict] = []
    unscored_categories: set[str] = set()
    scored_task_ids: list[str] = []

    system_digest = _sha256_of_text(candidate_config.system_instruction)

    for task in tasks:
        gen = adapter.generate(task.prompt, system_instruction=candidate_config.system_instruction, config=candidate_config.inference_config)

        if gen.error is not None or gen.text is None:
            generation_failures.append({
                "task_id": task.task_id, "category": task.category,
                "reason": gen.error or "no text returned", "latency_ms": gen.latency_ms,
            })
            continue

        raw_ref = _persist_raw_response(resolved_run_id, task.task_id, gen.text)

        if task.scoring_type == "llm_judge":
            unscored_categories.add(str(task.category))
            per_task_results.append({
                "task_id": task.task_id, "category": task.category, "passed": None,
                "scoring_type": task.scoring_type, "note": CANDIDATE_UNSCORED_MARKER,
                "latency_ms": gen.latency_ms, "raw_response_ref": raw_ref,
            })
            continue

        scorer_output = score_task(task, gen.text)
        per_task_results.append({
            "task_id": task.task_id, "category": task.category, "passed": scorer_output.get("passed"),
            "scoring_type": task.scoring_type, "scorer_output": scorer_output,
            "latency_ms": gen.latency_ms, "raw_response_ref": raw_ref,
        })
        scored_task_ids.append(task.task_id)

    completed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    per_category_summary: dict[str, dict] = {}
    for task in tasks:
        cat = str(task.category)
        per_category_summary.setdefault(cat, {"total": 0, "scored": 0, "passed": 0, "unscored": 0, "generation_failed": 0})
        per_category_summary[cat]["total"] += 1
    for entry in per_task_results:
        cat = str(entry["category"])
        if entry["passed"] is None:
            per_category_summary[cat]["unscored"] += 1
        else:
            per_category_summary[cat]["scored"] += 1
            if entry["passed"]:
                per_category_summary[cat]["passed"] += 1
    for entry in generation_failures:
        per_category_summary[str(entry["category"])]["generation_failed"] += 1

    deterministic_total = len(scored_task_ids)
    deterministic_passed = sum(1 for e in per_task_results if e["passed"] is True)
    deterministic_summary = {
        "total": deterministic_total,
        "passed": deterministic_passed,
        "pass_rate": round(deterministic_passed / deterministic_total, 4) if deterministic_total else None,
    }

    result = EvaluationResultManifest(
        run_id=resolved_run_id,
        candidate=candidate_config.candidate,
        upstream_model=candidate_config.upstream_model,
        artifact_repo=candidate_config.artifact_repo,
        exact_revision=candidate_config.exact_revision,
        tokenizer_revision=candidate_config.tokenizer_revision,
        backend=candidate_config.backend,
        quantization=candidate_config.quantization,
        inference_config=dict(candidate_config.inference_config),
        seed=candidate_config.seed,
        context_window_used=candidate_config.context_window_used,
        system_instruction_digest=f"sha256:{system_digest}",
        software_commit_sha=_current_git_sha(),
        hardware=dict(candidate_config.hardware),
        suite_id=suite_id, suite_version=suite_version,
        suite_content_digest=content_digest, suite_scoring_contract_digest=scoring_digest,
        per_task_results=per_task_results,
        per_category_summary=per_category_summary,
        deterministic_summary=deterministic_summary,
        unscored_categories=sorted(unscored_categories),
        generation_failures=generation_failures,
        started_at=started_at, completed_at=completed_at,
    )
    return result, scored_task_ids


class DryRunAdapter:
    """NOT A REAL MODEL. Validates the runner's plumbing only -- returns
    a fixed, clearly-labeled placeholder response for every prompt,
    never a real generation. Any EvaluationResultManifest produced using
    this adapter MUST be reported as a dry-run/synthetic validation
    artifact, never as a candidate baseline. See
    docs/orneur/phase-21/PHASE21B4_FOUNDATION_BASELINE_IMPLEMENTATION.md
    for how this is used (harness validation only) and where real
    baseline execution remains blocked pending owner-controlled compute."""

    def __init__(self, canned_response: str = "[DRY_RUN_PLACEHOLDER_RESPONSE -- NOT A REAL MODEL OUTPUT]"):
        self._canned_response = canned_response

    def generate(self, prompt: str, *, system_instruction: str, config: dict) -> GenerationResult:
        start = time.time()
        elapsed_ms = (time.time() - start) * 1000
        return GenerationResult(text=self._canned_response, latency_ms=elapsed_ms)
