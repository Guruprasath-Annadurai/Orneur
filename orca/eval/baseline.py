"""
Baseline recording <-> suite freeze transaction (Phase 21B.4).

Closes the exact gap named by the independent-audit requirement:
"The first real baseline result must be coupled transactionally/
fail-closed to persistent freezing of genesis-eval-v1. The evaluation
suite must never be silently modified after real model results have
been recorded against it."

Required lifecycle (conceptual, from the spec):

    load persisted suite
    -> verify suite identity/version
    -> verify content_digest
    -> verify scoring_contract_digest
    -> execute candidate evaluation            (caller's responsibility -- see orca.eval.runner)
    -> validate complete result
    -> persist immutable baseline/result record
    -> freeze genesis-eval-v1
    -> persist frozen suite manifest
    -> re-read persisted suite
    -> verify frozen=true
    -> verify digests unchanged

This module implements everything from "validate complete result"
onward as ONE fail-closed transaction
(`record_baseline_and_freeze_suite()`). The caller (a real evaluation
runner) is responsible for producing an already-populated, NOT-yet-
finalized `EvaluationResultManifest` -- this function never itself
invokes any model.

Failure modes this function explicitly prevents (see
tests/test_evaluation_baseline_freeze.py for the executable proof of
each):

  - A result exists but the suite remains mutable: the result is only
    ever written with `finalized=True` AFTER the suite freeze has been
    confirmed to have landed on disk (re-read, not merely trusted from
    memory). Before that point the result is either not persisted at
    all, or persisted with `finalized=False` and then deleted if the
    freeze fails.
  - The suite freezes before a failed/incomplete result: completeness
    is validated (`_validate_result_completeness()`) BEFORE the suite is
    ever touched.
  - A result references digests that differ from the persisted suite:
    checked explicitly against the loaded `EvaluationSuiteManifest`
    before anything is written.
  - A partially-written baseline appears valid: the staged result is
    written with `finalized=False`; only a fully-verified freeze flips
    it to `True` and re-saves it. A crash between staging and freeze
    confirmation leaves an on-disk result that is honestly
    `finalized=False`, never a false positive.
  - A later process overwrites `genesis-eval-v1` after the first
    successful baseline: enforced by
    `EvaluationSuiteManifest.save()`'s pre-existing frozen-on-disk
    guard (`EvaluationSuiteFrozenError`) -- this module never attempts
    to bypass it, and a second candidate's evaluation against an
    already-frozen suite takes a read-only verification path that never
    calls `.save()` on the suite at all.

Phase 21B.4.1 (§15-16) adversarial re-review, with a real ModelAdapter
now in place, found and fixed two further gaps:

  - A result could reference a DIFFERENT suite_id/suite_version than
    the one this transaction was actually recording against -- the
    function used its own `suite_id`/`suite_version` parameters to
    load/freeze the suite, but never cross-checked them against
    `result.suite_id`/`result.suite_version`. Reproduced live: a result
    object claiming `suite_id="totally-different-suite"` was silently
    accepted and finalized while the real, correct suite was frozen
    underneath it. Now checked explicitly and rejected
    (`BaselineIntegrityError`) before anything is touched.
  - Reusing a `run_id` across two different candidate results silently
    overwrote the first (already-finalized) result with the second's
    data, with no error. Reproduced live: candidate A's finalized
    result was replaced by candidate B's under the same run_id. Now
    checked explicitly (`DuplicateRunIdError`) before any write.
  - CONCURRENCY (§16): two processes could race to both observe an
    unfrozen suite, both stage a result, and both attempt to freeze --
    whichever's `.save()` lands last silently wins, while the other
    process's result would still be marked `finalized=True` in memory
    (and, worse, ALSO on disk, since nothing previously serialized the
    critical section). `_suite_freeze_lock()` below wraps the entire
    "load suite -> verify -> stage result -> freeze -> verify reload ->
    finalize" critical section in a POSIX advisory file lock
    (`fcntl.flock`, exclusive, blocking) keyed to `(suite_id,
    suite_version)`, so only one process can be inside that section for
    a given suite version at a time on a given host. This does not
    extend across physically separate machines/hosts (no distributed
    lock service exists in this project) -- stated honestly as the
    limitation of this mechanism, matching the project's existing
    single-host registry architecture (ORCA_HOME is a local filesystem
    tree, not a distributed store).
"""
from __future__ import annotations

import contextlib
import fcntl

from orca.config import ORCA_HOME
from orca.eval.genesis_suite import EvalTask, category_task_counts, compute_suite_digests
from orca.registry._ids import validate_id
from orca.registry.evaluation_result_manifest import EvaluationResultManifest
from orca.registry.evaluation_suite_manifest import EvaluationSuiteManifest

_LOCK_DIR = ORCA_HOME / "registry" / "evaluation_locks"


@contextlib.contextmanager
def _suite_freeze_lock(suite_id: str, suite_version: str):
    """POSIX advisory exclusive lock (fcntl.flock) serializing the
    baseline<->freeze critical section per (suite_id, suite_version) on
    THIS host. Blocks (does not fail) if another process on the same
    host currently holds the lock for the same suite version -- callers
    racing to become "the first baseline" simply queue, rather than
    both proceeding concurrently. Does NOT provide cross-host locking."""
    validate_id(suite_id, "suite_id")
    validate_id(suite_version, "version")
    _LOCK_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = _LOCK_DIR / f"{suite_id}-{suite_version}.lock"
    with open(lock_path, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


class BaselineIntegrityError(ValueError):
    """The candidate result's recorded suite digests, or the currently
    loaded task list, do not match the persisted suite manifest -- the
    baseline transaction refuses to proceed."""


class IncompleteResultError(ValueError):
    """The candidate result does not account for every task in the
    suite (a per_task_results entry OR a generation_failures entry for
    every task_id) -- denominator integrity would be violated if this
    were accepted as a baseline."""


class BaselineFreezeFailed(RuntimeError):
    """The suite-freeze half of the transaction did not complete and
    verify successfully -- any staged result has been rolled back
    (deleted), and the suite was never left in a falsely-frozen state."""


class DuplicateRunIdError(ValueError):
    """A finalized EvaluationResultManifest already exists on disk under
    this exact run_id -- refusing to silently overwrite a prior
    candidate's finalized result. Found via adversarial review this
    closure (spec §15's 'duplicate run IDs' attack): reusing a run_id
    across two different candidates previously overwrote the first
    candidate's finalized result with the second's, with no error at
    all."""


def _validate_result_completeness(result: EvaluationResultManifest, task_ids: list[str]) -> None:
    accounted_for: set[str] = set()
    for entry in result.per_task_results:
        task_id = entry.get("task_id")
        if task_id is None:
            raise IncompleteResultError(f"per_task_results entry missing task_id: {entry!r}")
        accounted_for.add(task_id)
    for entry in result.generation_failures:
        task_id = entry.get("task_id")
        if task_id is None:
            raise IncompleteResultError(f"generation_failures entry missing task_id: {entry!r}")
        accounted_for.add(task_id)

    # Tasks in categories explicitly marked unscored (llm_judge categories
    # this closure does not execute) are exempt from the completeness
    # requirement -- they were never expected to have a per-task result.
    missing = set(task_ids) - accounted_for
    if missing:
        # Filter out tasks whose category is in unscored_categories --
        # requires the caller's task list, which this function doesn't
        # have directly; callers pass task_ids already filtered to only
        # the tasks that were EXPECTED to be scored (see
        # orca.eval.runner.run_suite()'s contract).
        raise IncompleteResultError(
            f"Result is missing accounting for {len(missing)} task(s) -- denominator integrity "
            f"violated: {sorted(missing)[:10]}{'...' if len(missing) > 10 else ''}"
        )
    if result.completed_at is None:
        raise IncompleteResultError("Result has no completed_at timestamp -- evaluation did not finish")


def record_baseline_and_freeze_suite(
    *,
    tasks: list[EvalTask],
    result: EvaluationResultManifest,
    scored_task_ids: list[str],
    suite_id: str = "genesis-eval",
    suite_version: str = "v1",
) -> EvaluationResultManifest:
    """The one fail-closed entry point for recording a real evaluation
    result against `genesis-eval-v1`. `tasks` is the CURRENT in-code
    task list (from `orca.eval.genesis_suite.all_tasks()`); `result` is
    an already-populated, NOT-yet-finalized `EvaluationResultManifest`
    (caller sets `finalized=False`, `is_first_baseline=False` -- this
    function decides both); `scored_task_ids` is the set of task_ids the
    caller actually expected to score (i.e. excluding unscored llm_judge
    categories), used for the completeness check.

    Returns the finalized, persisted result on success. Raises
    `BaselineIntegrityError`, `IncompleteResultError`,
    `DuplicateRunIdError`, or `BaselineFreezeFailed` on any failure -- in
    every failure case, no result claiming to be a valid finalized
    baseline is left on disk.

    Phase 21B.4.1 (§16): the entire transaction runs inside
    `_suite_freeze_lock(suite_id, suite_version)` -- a per-host,
    per-suite-version exclusive lock, so two concurrent calls for the
    same suite version can never both believe they froze it first."""
    with _suite_freeze_lock(suite_id, suite_version):
        return _record_baseline_and_freeze_suite_locked(
            tasks=tasks, result=result, scored_task_ids=scored_task_ids,
            suite_id=suite_id, suite_version=suite_version,
        )


def _record_baseline_and_freeze_suite_locked(
    *,
    tasks: list[EvalTask],
    result: EvaluationResultManifest,
    scored_task_ids: list[str],
    suite_id: str,
    suite_version: str,
) -> EvaluationResultManifest:
    """The actual transaction body -- ONLY ever called from inside
    record_baseline_and_freeze_suite()'s lock. Not exported."""
    # Phase 21B.4.1 (§15) adversarial-review fixes:
    if result.suite_id != suite_id or result.suite_version != suite_version:
        raise BaselineIntegrityError(
            f"result.suite_id/suite_version ({result.suite_id!r}, {result.suite_version!r}) does not "
            f"match the suite this transaction is recording against ({suite_id!r}, {suite_version!r}) "
            "-- refusing to persist a result that would misrepresent which suite it was scored against."
        )
    try:
        existing = EvaluationResultManifest.load(result.run_id)
        if existing.finalized:
            raise DuplicateRunIdError(
                f"A finalized EvaluationResultManifest already exists for run_id={result.run_id!r} "
                f"(candidate={existing.candidate!r}) -- refusing to silently overwrite it. Use a new, "
                "unique run_id for each evaluation run."
            )
    except FileNotFoundError:
        pass  # no prior result under this run_id -- normal case

    task_ids, content_digest, scoring_digest = compute_suite_digests(tasks)

    try:
        suite_manifest = EvaluationSuiteManifest.load(suite_id, suite_version)
        suite_existed = True
    except FileNotFoundError:
        suite_manifest = EvaluationSuiteManifest(
            suite_id=suite_id, version=suite_version, task_ids=task_ids,
            content_digest=content_digest, scoring_contract_digest=scoring_digest,
            creation_code_sha=result.software_commit_sha, category_task_counts=category_task_counts(tasks),
        )
        suite_existed = False

    ok, msg = suite_manifest.verify_against_tasks(tasks)
    if not ok:
        raise BaselineIntegrityError(f"Suite {suite_id}-{suite_version} does not match the current task list: {msg}")

    if result.suite_content_digest != suite_manifest.content_digest:
        raise BaselineIntegrityError(
            f"Result's suite_content_digest ({result.suite_content_digest}) does not match the "
            f"persisted suite manifest's content_digest ({suite_manifest.content_digest})"
        )
    if result.suite_scoring_contract_digest != suite_manifest.scoring_contract_digest:
        raise BaselineIntegrityError(
            f"Result's suite_scoring_contract_digest ({result.suite_scoring_contract_digest}) does not "
            f"match the persisted suite manifest's scoring_contract_digest ({suite_manifest.scoring_contract_digest})"
        )

    _validate_result_completeness(result, scored_task_ids)

    if suite_manifest.frozen:
        # Suite already frozen by an earlier baseline -- this candidate's
        # result is persisted as a normal (non-freeze-triggering) finalized
        # result. The suite itself is never touched (no .save() call) --
        # EvaluationSuiteManifest.save()'s own frozen-on-disk guard would
        # refuse it anyway, but this path doesn't even attempt it.
        result.is_first_baseline = False
        result.finalized = True
        result.save()
        return result

    if not suite_existed:
        suite_manifest.save()  # first-ever registration of this suite version, still unfrozen

    # Stage the result BEFORE touching the freeze -- explicitly NOT
    # finalized yet, so a crash here leaves an honestly-incomplete
    # on-disk record, never a false positive.
    result.is_first_baseline = True
    result.finalized = False
    result.save()

    try:
        suite_manifest.freeze()
        suite_manifest.save()
    except Exception as exc:
        result.delete()
        raise BaselineFreezeFailed(
            f"Freezing {suite_id}-{suite_version} failed after the result was staged -- the staged "
            f"result has been rolled back (deleted): {exc}"
        ) from exc

    reloaded = EvaluationSuiteManifest.load(suite_id, suite_version)
    if not reloaded.frozen:
        result.delete()
        raise BaselineFreezeFailed(
            f"Suite {suite_id}-{suite_version} does not show frozen=True after reload from disk -- "
            "the staged result has been rolled back (deleted)."
        )
    if reloaded.content_digest != content_digest or reloaded.scoring_contract_digest != scoring_digest:
        result.delete()
        raise BaselineFreezeFailed(
            f"Suite {suite_id}-{suite_version}'s persisted digests changed unexpectedly during the "
            "freeze transaction -- the staged result has been rolled back (deleted)."
        )

    result.finalized = True
    result.save()
    return result
