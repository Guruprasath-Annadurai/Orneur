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
import hashlib
import json
import re
from pathlib import Path

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


class MissingGenerationProvenanceError(ValueError):
    """Phase 21B.4.8.2 baseline gate, TIGHTENED in Phase 21B.4.8.3: a
    real baseline may never be finalized without a trace back to the
    exact sealed generation bundle it was scored from. Independent audit
    found that the 21B.4.8.2 version of this gate only required a digest
    WHEN a caller happened to declare provenance_kind=
    "real_generation_artifact" -- leaving "unspecified" (the field's
    backward-compatible default) as a silent bypass, since nothing
    forced a real evaluation to declare itself at all.
    record_baseline_and_freeze_suite() now REQUIRES provenance_kind ==
    "real_generation_artifact" outright (see `_validate_result_provenance`)
    -- "unspecified" and "synthetic_test" are both rejected here. Legacy
    stored manifests with provenance_kind="unspecified" may still be
    LOADED/read (EvaluationResultManifest.load() is unaffected); this
    error only ever blocks a NEW call to the freeze transaction."""


class GenerationArtifactMismatchError(ValueError):
    """Phase 21B.4.8.3 (spec section 4/13): the result's declared
    generation-artifact provenance (digest, or the identity fields
    re-derived from the actual sealed artifact on disk) does not match
    what is actually being finalized -- e.g. a syntactically valid-
    looking digest that does not correspond to any real sealed artifact
    for this run_id, a digest that belongs to a DIFFERENT run_id's
    artifact, or an artifact whose candidate/revision/suite/config
    identity disagrees with the result claiming to have been scored from
    it. This is also the TOCTOU re-verification failure: the sealed
    artifact is re-read and re-verified at FINALIZATION time, never
    trusted solely from an earlier scoring-time check, so bytes altered
    or replaced between scoring and finalization are caught here too."""


class GenerationArtifactMissingError(ValueError):
    """Phase 21B.4.8.3 (spec section 13): no sealed generation artifact
    (or its independently-retained sidecar digest) could be found on
    disk for the result's run_id at baseline-finalization time -- a real
    baseline can never be finalized without being able to independently
    re-verify its provenance, even if an earlier scoring-time check
    passed. Covers both "never existed" and "removed since scoring"."""


class RawEvidencePreservationError(ValueError):
    """Phase 21B.4.10 mandatory pre-freeze gate (carried forward from
    the Phase 21B.4.8.3 audit finding, restated as a hard prerequisite
    in Phase 21B.4.9's execution plan): a successful generation record's
    raw response is no longer intact on disk at baseline-finalization
    time -- missing, moved outside the canonical artifact root, not a
    regular file, wrong byte length, wrong SHA-256, or fails to decode
    as UTF-8. This is a genuine TOCTOU gap `_validate_result_generation_
    provenance()`'s bundle-level re-hash does not close by itself: the
    sealed manifest's bundle bytes and each individual raw-response file
    live in separate content-addressed stores, so re-verifying the
    bundle proves the manifest's own claims are self-consistent but says
    nothing about whether every raw-response file it POINTS TO is still
    intact. The suite must remain unfrozen when this check fails."""


class DuplicateRunIdError(ValueError):
    """A finalized EvaluationResultManifest already exists on disk under
    this exact run_id -- refusing to silently overwrite a prior
    candidate's finalized result. Found via adversarial review this
    closure (spec §15's 'duplicate run IDs' attack): reusing a run_id
    across two different candidates previously overwrote the first
    candidate's finalized result with the second's, with no error at
    all."""


def _validate_result_completeness(result: EvaluationResultManifest, tasks: list[EvalTask]) -> None:
    """Phase 21B.4.8.1 fix: 'expected' is derived ONLY from `tasks` (the
    live-verified suite this transaction is recording against), never
    from a caller-supplied subset like `scored_task_ids` -- an
    independent audit found that using the scoring phase's own observed
    output as the definition of 'what was expected' let a task dropped
    in cross-machine transfer silently validate itself as complete. This
    also now explicitly detects DUPLICATE task_id entries, which the
    prior set-based accounting silently absorbed without ever flagging.

    Every task in `tasks` -- including llm_judge categories, which
    still receive a per_task_results entry (passed=None, an explicit
    unscored marker) per orca.eval.runner.run_scoring_phase()'s
    contract -- must appear in EXACTLY ONE of per_task_results or
    generation_failures. Missing transport data is an integrity error,
    never silently treated as equivalent to a generation failure."""
    expected_task_ids = {t.task_id for t in tasks}

    seen: dict[str, int] = {}
    for entry in result.per_task_results:
        task_id = entry.get("task_id")
        if task_id is None:
            raise IncompleteResultError(f"per_task_results entry missing task_id: {entry!r}")
        seen[task_id] = seen.get(task_id, 0) + 1
    for entry in result.generation_failures:
        task_id = entry.get("task_id")
        if task_id is None:
            raise IncompleteResultError(f"generation_failures entry missing task_id: {entry!r}")
        seen[task_id] = seen.get(task_id, 0) + 1

    missing = sorted(expected_task_ids - set(seen.keys()))
    unknown = sorted(set(seen.keys()) - expected_task_ids)
    duplicates = sorted(tid for tid, count in seen.items() if count > 1)

    problems = []
    if missing:
        problems.append(f"missing {len(missing)} expected task(s): {missing[:10]}{'...' if len(missing) > 10 else ''}")
    if duplicates:
        problems.append(f"{len(duplicates)} duplicate task_id(s): {duplicates[:10]}{'...' if len(duplicates) > 10 else ''}")
    if unknown:
        problems.append(f"{len(unknown)} unknown task_id(s) not in the suite: {unknown[:10]}")
    if problems:
        raise IncompleteResultError(
            "Result failed denominator-integrity validation against the verified suite -- " + "; ".join(problems)
        )
    if result.completed_at is None:
        raise IncompleteResultError("Result has no completed_at timestamp -- evaluation did not finish")


_DIGEST_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


_TEXT_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _verify_raw_evidence_before_freeze(manifest, tasks: list[EvalTask]) -> None:
    """Phase 21B.4.10 mandatory pre-freeze raw-evidence gate, hardened in
    Phase 21B.4.10.1. Called from `_validate_result_generation_provenance()`
    immediately after the sealed bundle's own bytes and identity have
    been re-verified, using that SAME already-loaded manifest (never
    re-reading the sealed artifact a third time) -- as close to the
    irreversible suite freeze as this transaction's structure allows,
    inside the suite-freeze lock. Never relies solely on the earlier
    scoring-time raw-response verification
    (`score_verified_generation_artifact()`'s
    `read_and_verify_raw_response()` calls), which happened at a
    different point in time and cannot detect anything that changed
    since.

    1. Re-reconciles the manifest against the live-verified suite
       (`orca.eval.generation_artifact.verify_against_suite`) --
       missing transport evidence is an INTEGRITY FAILURE, never
       silently treated as equivalent to a generation failure.
    2. For every record with `error is not None` (an explicit
       generation failure): requires `raw_response_ref`, `text_sha256`,
       and `byte_length` to ALL be `None` -- Phase 21B.4.10.1 §13's
       invariant: a record must never simultaneously claim a generation
       failure AND carry successful-looking raw-response evidence.
    3. For every record with `error is None` (a claimed-successful
       generation), independently re-verifies, ALL MANDATORY (Phase
       21B.4.10.1 §11: hash and length are no longer optional fields):
       - `raw_response_ref` is a non-empty string;
       - `text_sha256` is present and is exactly 64 lowercase hex
         characters;
       - `byte_length` is present and is a non-negative integer;
       - `raw_response_ref` is not a symlink itself (Phase 21B.4.10.1
         §12: rejects symlink indirection that would make artifact
         ownership ambiguous);
       - it resolves to an existing regular file;
       - it resolves specifically UNDER `GENERATION_ARTIFACT_DIR /
         manifest.run_id` (Phase 21B.4.10.1 §12: run-specific artifact
         binding -- a response belonging to a DIFFERENT run's directory
         is rejected even when its bytes/hash happen to be identical,
         not merely "somewhere under the global canonical root");
       - its exact byte length matches the manifest's recorded
         `byte_length`;
       - its SHA-256 matches the manifest's recorded `text_sha256`;
       - its bytes decode as UTF-8.

    Raises `GenerationArtifactIntegrityError` (suite-coverage failures,
    from `verify_against_suite`) or `RawEvidencePreservationError`
    (raw-response-level failures) -- in either case the caller must not
    proceed to freeze the suite."""
    from orca.eval.generation_artifact import GENERATION_ARTIFACT_DIR, verify_against_suite

    verify_against_suite(manifest, tasks)

    run_root = (Path(GENERATION_ARTIFACT_DIR) / manifest.run_id).resolve()

    for record in manifest.records:
        task_id = record.get("task_id")
        raw_ref = record.get("raw_response_ref")
        expected_sha = record.get("text_sha256")
        expected_len = record.get("byte_length")

        if record.get("error") is not None:
            # Phase 21B.4.10.1 §13: an explicit generation failure must
            # never simultaneously carry successful-looking raw-response
            # evidence -- that would be a self-contradictory record.
            if raw_ref is not None or expected_sha is not None or expected_len is not None:
                raise RawEvidencePreservationError(
                    f"Task {task_id!r} has error={record.get('error')!r} set (a generation failure) but "
                    f"also carries raw_response_ref={raw_ref!r}/text_sha256={expected_sha!r}/"
                    f"byte_length={expected_len!r} -- a record must not simultaneously claim a generation "
                    "failure and successful raw-response evidence."
                )
            continue  # legitimate, accounted-for generation failure -- not raw-evidence-checked

        # ── Successful record: hash and length are now MANDATORY, never optional. ──
        if not raw_ref or not isinstance(raw_ref, str):
            raise RawEvidencePreservationError(
                f"Task {task_id!r} has no (or a non-string) raw_response_ref recorded despite error=None "
                "-- missing transport evidence is an integrity failure, not a generation failure."
            )
        if not expected_sha or not isinstance(expected_sha, str) or not _TEXT_SHA256_RE.match(expected_sha):
            raise RawEvidencePreservationError(
                f"Task {task_id!r} has text_sha256={expected_sha!r}, which is not a well-formed "
                "64-character lowercase hex SHA-256 digest -- a successful record must carry a mandatory, "
                "well-formed hash."
            )
        if not isinstance(expected_len, int) or isinstance(expected_len, bool) or expected_len < 0:
            raise RawEvidencePreservationError(
                f"Task {task_id!r} has byte_length={expected_len!r}, which is not a non-negative integer "
                "-- a successful record must carry a mandatory, valid byte_length."
            )

        path = Path(raw_ref)
        if path.is_symlink():
            raise RawEvidencePreservationError(
                f"Task {task_id!r} raw_response_ref {raw_ref!r} is itself a symlink -- refusing to trust "
                "symlink indirection, which would make the artifact's ownership ambiguous."
            )
        try:
            resolved = path.resolve(strict=True)
        except (FileNotFoundError, RuntimeError) as exc:
            raise RawEvidencePreservationError(
                f"Task {task_id!r} raw_response_ref {raw_ref!r} does not exist (or could not be "
                f"resolved) at baseline-finalization time -- present at scoring time, gone now: {exc}"
            ) from exc

        # Phase 21B.4.10.1 §12: run-specific artifact binding -- must
        # resolve under THIS run's own subdirectory, not merely anywhere
        # under the global canonical root (which would let a response
        # belonging to a different run's directory be reused/confused).
        if resolved != run_root and run_root not in resolved.parents:
            raise RawEvidencePreservationError(
                f"Task {task_id!r} raw_response_ref {raw_ref!r} resolves to {resolved}, which is not "
                f"under this run's own canonical artifact directory {run_root} -- refusing to trust a "
                "path belonging to a different run, or one that could have been redirected/escaped "
                "since scoring time."
            )
        if not resolved.is_file():
            raise RawEvidencePreservationError(
                f"Task {task_id!r} raw_response_ref {raw_ref!r} does not resolve to a regular file "
                "at baseline-finalization time."
            )

        data = resolved.read_bytes()
        if len(data) != expected_len:
            raise RawEvidencePreservationError(
                f"Task {task_id!r} raw_response_ref {raw_ref!r} byte length ({len(data)}) no longer "
                f"matches the manifest's recorded byte_length ({expected_len}) -- altered since "
                "scoring time."
            )
        actual_sha = hashlib.sha256(data).hexdigest()
        if actual_sha != expected_sha:
            raise RawEvidencePreservationError(
                f"Task {task_id!r} raw_response_ref {raw_ref!r} SHA-256 ({actual_sha}) no longer "
                f"matches the manifest's recorded hash ({expected_sha}) -- altered or replaced since "
                "scoring time."
            )
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RawEvidencePreservationError(
                f"Task {task_id!r} raw_response_ref {raw_ref!r} no longer decodes as UTF-8 text at "
                f"baseline-finalization time: {exc}"
            ) from exc


def _validate_result_generation_provenance(result: EvaluationResultManifest, tasks: list[EvalTask]) -> None:
    """Phase 21B.4.8.3 (spec sections 3-4, 13): a syntactically valid
    digest string is NOT provenance. Called only once
    `result.provenance_kind == "real_generation_artifact"` has already
    been confirmed by `_validate_result_provenance`. Performs, in order:

      1. Format-validates `generation_artifact_digest` (64-char lowercase
         hex) and `generation_artifact_schema_version` (must equal the
         one supported schema version) -- rejects a malformed or
         arbitrary-looking digest before touching disk at all.
      2. RE-READS the canonical sealed artifact for `result.run_id` from
         disk (orca.eval.generation_artifact
         .read_sealed_generation_artifact()) -- never trusts a digest
         string alone. Missing artifact or sidecar ->
         GenerationArtifactMissingError.
      3. Requires `result.generation_artifact_digest` to equal the
         sidecar's OWN independently-retained expected digest -- a
         mismatch means the result claims provenance from a DIFFERENT
         artifact than what is actually on disk for this run_id.
      4. Calls `load_and_verify_generation_artifact()` -- hashes the
         ACTUAL bytes on disk against that same expected digest AGAIN,
         at finalization time, not merely trusting an earlier scoring-
         time check. This closes the TOCTOU window: if the artifact was
         altered or replaced after scoring but before baseline
         finalization, this re-hash catches it here.
      5. Cross-checks the re-verified manifest's identity fields against
         the result's OWN recorded fields (run_id, candidate,
         upstream_model, artifact_repo, exact_revision,
         tokenizer_revision, backend, suite_id, suite_version, suite
         digests, system_instruction_digest, and an independently
         recomputed generation_config_digest from
         result.inference_config) -- any disagreement is
         GenerationArtifactMismatchError.
      6. Phase 21B.4.10: calls `_verify_raw_evidence_before_freeze()` --
         the mandatory pre-freeze raw-evidence gate re-reconciling the
         manifest against `tasks` and independently re-verifying every
         successful record's raw-response file (existence, canonical-
         root containment, byte_length, SHA-256, UTF-8 decodability) at
         finalization time, never relying solely on the earlier
         scoring-time check."""
    from orca.eval.generation_artifact import (
        GENERATION_ARTIFACT_SCHEMA_VERSION,
        GenerationArtifactIntegrityError,
        load_and_verify_generation_artifact,
        read_sealed_generation_artifact,
    )

    digest = result.generation_artifact_digest
    if not digest or not _DIGEST_HEX_RE.match(digest):
        raise GenerationArtifactMismatchError(
            f"Result run_id={result.run_id!r} generation_artifact_digest={digest!r} is not a "
            "well-formed 64-character lowercase hex SHA-256 digest -- a syntactically valid-looking "
            "digest is not provenance."
        )
    if result.generation_artifact_schema_version != GENERATION_ARTIFACT_SCHEMA_VERSION:
        raise GenerationArtifactMismatchError(
            f"Result run_id={result.run_id!r} generation_artifact_schema_version="
            f"{result.generation_artifact_schema_version!r} does not match the supported schema "
            f"{GENERATION_ARTIFACT_SCHEMA_VERSION!r}."
        )

    try:
        serialized, sidecar_expected_digest = read_sealed_generation_artifact(result.run_id)
    except GenerationArtifactIntegrityError as exc:
        raise GenerationArtifactMissingError(
            f"No sealed generation artifact could be re-read for run_id={result.run_id!r} at baseline "
            f"finalization time -- a real baseline can never be finalized without independently "
            f"re-verifying its provenance, even if an earlier scoring-time check passed: {exc}"
        ) from exc

    if digest != sidecar_expected_digest:
        raise GenerationArtifactMismatchError(
            f"Result run_id={result.run_id!r} generation_artifact_digest ({digest}) does not match "
            f"the canonical sealed artifact's independently-retained sidecar digest "
            f"({sidecar_expected_digest}) -- the result claims provenance from a different artifact "
            "than what is actually on disk for this run_id."
        )

    try:
        verified = load_and_verify_generation_artifact(serialized, sidecar_expected_digest)
    except GenerationArtifactIntegrityError as exc:
        raise GenerationArtifactMismatchError(
            f"Sealed generation artifact for run_id={result.run_id!r} failed re-verification at "
            f"baseline-finalization time -- its bytes on disk no longer match the retained digest "
            f"(TOCTOU: altered or replaced since scoring time): {exc}"
        ) from exc

    manifest = verified.manifest
    expected_generation_config_digest = "sha256:" + hashlib.sha256(
        json.dumps(result.inference_config, sort_keys=True).encode("utf-8")
    ).hexdigest()

    checks = [
        ("run_id", manifest.run_id, result.run_id),
        ("candidate", manifest.candidate, result.candidate),
        ("upstream_model", manifest.upstream_model, result.upstream_model),
        ("artifact_repo", manifest.artifact_repo, result.artifact_repo),
        ("exact_revision", manifest.exact_revision, result.exact_revision),
        ("tokenizer_revision", manifest.tokenizer_revision, result.tokenizer_revision),
        ("backend", manifest.backend, result.backend),
        ("suite_id", manifest.suite_id, result.suite_id),
        ("suite_version", manifest.suite_version, result.suite_version),
        ("suite_content_digest", manifest.suite_content_digest, result.suite_content_digest),
        ("suite_scoring_contract_digest", manifest.suite_scoring_contract_digest, result.suite_scoring_contract_digest),
        ("system_instruction_digest", manifest.system_instruction_digest, result.system_instruction_digest),
        ("generation_config_digest", manifest.generation_config_digest, expected_generation_config_digest),
    ]
    mismatches = [(n, g, w) for n, g, w in checks if g != w]
    if mismatches:
        details = "; ".join(f"{n}: artifact={g!r} != result={w!r}" for n, g, w in mismatches)
        raise GenerationArtifactMismatchError(
            f"Re-verified sealed generation artifact for run_id={result.run_id!r} does not match the "
            f"result being finalized -- refusing to freeze a baseline whose claimed provenance "
            f"disagrees with the actual artifact on disk: {details}"
        )

    _verify_raw_evidence_before_freeze(manifest, tasks)


def _validate_result_provenance(result: EvaluationResultManifest, tasks: list[EvalTask]) -> None:
    """Phase 21B.4.8.3 baseline gate (tightened from 21B.4.8.2):
    `record_baseline_and_freeze_suite()` is the REAL baseline/freeze
    transaction, so it now REQUIRES `provenance_kind ==
    "real_generation_artifact"` outright -- `"unspecified"` (the field's
    backward-compatible default, kept only so historical manifests can
    still be READ) and `"synthetic_test"` (harness/dry-run results, e.g.
    from `run_suite()` or the legacy `run_scoring_phase_from_artifact()`)
    are both REJECTED here. An independent audit found that only
    requiring a digest WHEN a caller happened to declare
    "real_generation_artifact" left "unspecified" as a silent bypass,
    since nothing forced a real evaluation to declare itself at all.

    Once `provenance_kind` is confirmed real, delegates to
    `_validate_result_generation_provenance()` to re-verify the actual
    sealed artifact on disk -- a bare digest string is never sufficient
    evidence on its own."""
    if result.provenance_kind != "real_generation_artifact":
        raise MissingGenerationProvenanceError(
            f"Result run_id={result.run_id!r} has provenance_kind={result.provenance_kind!r} -- "
            "record_baseline_and_freeze_suite() only finalizes results with provenance_kind="
            "'real_generation_artifact' (produced exclusively by "
            "orca.eval.runner.score_verified_generation_artifact()). Synthetic/dry-run/harness "
            "results (provenance_kind='synthetic_test') and results with unset/legacy provenance "
            "(provenance_kind='unspecified') must never freeze the real evaluation suite -- use a "
            "separate non-freezing persistence path for those."
        )
    _validate_result_generation_provenance(result, tasks)


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
    function decides both); `scored_task_ids` is the caller's own
    record of which task_ids it deterministically scored (i.e.
    excluding unscored llm_judge categories) -- retained in the
    manifest/return value for reporting, but Phase 21B.4.8.1 no longer
    uses it as the SOURCE OF TRUTH for the completeness check. An
    independent audit found that doing so let a task dropped in
    cross-machine transfer silently validate itself as complete, since
    `scored_task_ids` was itself derived from whatever records the
    scoring phase happened to receive. The completeness check now
    derives "what was expected" ONLY from `tasks` directly (see
    `_validate_result_completeness`).

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

    _validate_result_completeness(result, tasks)
    _validate_result_provenance(result, tasks)

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
