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
    persisted separately or by content-addressed reference').

    Phase 21B.4.8.1: delegates to orca.eval.generation_artifact's
    durable, ORCA_HOME-canonical store (not the legacy RAW_RESPONSE_DIR
    below, kept only so any external reference to that constant doesn't
    break) -- this is the store an ORCHESTRATOR persists into with text
    a GPU worker returned to it, not an assumption that a path created
    on the generation host is readable from wherever scoring runs."""
    if text is None:
        return None
    from orca.eval.generation_artifact import persist_raw_response

    ref, _digest, _length = persist_raw_response(run_id, task_id, text)
    return ref


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


@dataclass(frozen=True)
class GenerationRecord:
    """One task's generation OUTCOME -- text plus everything scoring
    needs, but not yet scored. This is the artifact that crosses the
    trust/machine boundary (Phase 21B.4.8 spec section 3): a Modal GPU
    worker can produce a list of these and hand them off (as JSON, a
    file, a queue message -- transport is the caller's choice) to a
    completely separate, Docker-equipped machine that never needed a
    GPU. Model-generated text is untrusted DATA here, never executed."""
    task_id: str
    category: int
    scoring_type: str
    text: str | None
    error: str | None
    latency_ms: float
    raw_response_ref: str | None
    text_sha256: str | None = None
    byte_length: int | None = None


@dataclass(frozen=True)
class RemoteGenerationRecord:
    """What a trusted inference worker (e.g. a Modal GPU function) hands
    back to the ORNEUR orchestrator for one task -- deliberately
    contains NO raw_response_ref / local-path field of any kind (Phase
    21B.4.8.2 Blocker 1). The worker must never decide, construct, or
    return anything resembling a durable artifact path; that
    responsibility belongs exclusively to the orchestrator's
    materialize_generation_artifact() step, which runs against the
    orchestrator's OWN ORCA_HOME, never the worker's ephemeral
    filesystem."""
    task_id: str
    category: int
    scoring_type: str
    text: str | None
    error: str | None
    latency_ms: float
    provider_metadata: dict = field(default_factory=dict)


def run_remote_generation_phase(
    adapter: ModelAdapter,
    candidate_config: CandidateConfig,
    tasks: list[EvalTask],
) -> list[RemoteGenerationRecord]:
    """Calls `adapter.generate()` for every task and returns plain
    RemoteGenerationRecords -- no persistence, no run_id, no local
    filesystem path of any kind. This is the function safe to execute
    ENTIRELY on a trusted-inference-only remote worker (e.g. a Modal GPU
    function): it never touches ORCA_HOME or any filesystem, so it has
    no way to produce a "durable artifact path" that could be mistaken
    for one. The caller/orchestrator is responsible for calling
    materialize_generation_artifact() with the returned list, on its own
    machine (Phase 21B.4.8.2 Blocker 1)."""
    records: list[RemoteGenerationRecord] = []
    for task in tasks:
        gen = adapter.generate(task.prompt, system_instruction=candidate_config.system_instruction, config=candidate_config.inference_config)
        if gen.error is not None or gen.text is None:
            records.append(RemoteGenerationRecord(
                task_id=task.task_id, category=task.category, scoring_type=task.scoring_type,
                text=None, error=gen.error or "no text returned", latency_ms=gen.latency_ms,
            ))
            continue
        records.append(RemoteGenerationRecord(
            task_id=task.task_id, category=task.category, scoring_type=task.scoring_type,
            text=gen.text, error=None, latency_ms=gen.latency_ms,
        ))
    return records


def _validate_remote_records_against_tasks(remote_records: list[RemoteGenerationRecord], tasks: list[EvalTask]) -> None:
    """The same class of fail-closed reconciliation as
    orca.eval.generation_artifact.verify_against_suite(), but applied to
    RemoteGenerationRecords BEFORE any persistence happens (Phase
    21B.4.8.2 Blocker 1: "orchestrator validates expected task coverage"
    is a step that must occur before "orchestrator persists response
    bytes"). Raises GenerationArtifactIntegrityError on any missing,
    duplicate, unknown, or category/scoring_type-mismatched remote
    record -- the orchestrator must never start writing into canonical
    storage from a transport batch it hasn't first confirmed is
    complete and correct."""
    from orca.eval.generation_artifact import GenerationArtifactIntegrityError

    suite_by_id = {t.task_id: t for t in tasks}
    suite_task_ids = set(suite_by_id.keys())

    seen: dict[str, int] = {}
    unknown: list[str] = []
    mismatched: list[str] = []
    for record in remote_records:
        seen[record.task_id] = seen.get(record.task_id, 0) + 1
        if record.task_id not in suite_by_id:
            unknown.append(record.task_id)
            continue
        suite_task = suite_by_id[record.task_id]
        if record.category != suite_task.category or record.scoring_type != suite_task.scoring_type:
            mismatched.append(record.task_id)

    duplicates = sorted(tid for tid, count in seen.items() if count > 1)
    missing = sorted(suite_task_ids - set(seen.keys()))

    problems = []
    if missing:
        problems.append(f"missing {len(missing)} expected task(s) in remote generation records: {missing[:10]}{'...' if len(missing) > 10 else ''}")
    if duplicates:
        problems.append(f"{len(duplicates)} duplicate remote generation record(s): {duplicates[:10]}{'...' if len(duplicates) > 10 else ''}")
    if unknown:
        problems.append(f"{len(unknown)} unknown task_id(s) in remote generation records: {sorted(set(unknown))[:10]}")
    if mismatched:
        problems.append(f"{len(mismatched)} remote record(s) with category/scoring_type mismatched against the suite: {sorted(mismatched)[:10]}")

    if problems:
        raise GenerationArtifactIntegrityError(
            "Remote generation records failed coverage validation against the verified suite BEFORE "
            "materialization -- refusing to persist a possibly-incomplete or corrupted transport batch: "
            + "; ".join(problems)
        )


def run_generation_phase(
    adapter: ModelAdapter,
    candidate_config: CandidateConfig,
    tasks: list[EvalTask],
    *,
    run_id: str,
) -> list[GenerationRecord]:
    """Local/same-machine convenience path: calls `adapter.generate()`
    for every task and persists raw responses into the durable,
    content-addressed store (orca.eval.generation_artifact
    .persist_raw_response). Does NOT score anything -- never imports or
    calls orca.eval.genesis_suite.score_task, and therefore never needs
    a SandboxBackend/Docker. This is the half of run_suite() that is
    safe to run on a trusted-inference-only machine with no local
    code-execution sandbox available at all.

    Built on top of run_remote_generation_phase() (the same generation-
    execution implementation the cross-machine-safe path uses) plus a
    per-record persist step -- there is one generation-execution
    implementation, not two. Unlike materialize_generation_artifact(),
    this function does not need an up-front coverage-validation pass:
    it is itself the `for task in tasks` loop, so it cannot produce a
    missing/duplicate/unknown record the way a transported batch of
    RemoteGenerationRecords could.

    Each record's text_sha256/byte_length are recorded so a later
    GenerationArtifactManifest (build_generation_artifact_manifest())
    can be independently verified before scoring, per Phase 21B.4.8.1's
    denominator-integrity fix."""
    from orca.eval.generation_artifact import persist_raw_response

    remote_records = run_remote_generation_phase(adapter, candidate_config, tasks)
    records: list[GenerationRecord] = []
    for rr in remote_records:
        if rr.error is not None or rr.text is None:
            records.append(GenerationRecord(
                task_id=rr.task_id, category=rr.category, scoring_type=rr.scoring_type,
                text=None, error=rr.error or "no text returned", latency_ms=rr.latency_ms, raw_response_ref=None,
            ))
            continue
        raw_ref, digest, length = persist_raw_response(run_id, rr.task_id, rr.text)
        records.append(GenerationRecord(
            task_id=rr.task_id, category=rr.category, scoring_type=rr.scoring_type,
            text=rr.text, error=None, latency_ms=rr.latency_ms, raw_response_ref=raw_ref,
            text_sha256=digest, byte_length=length,
        ))
    return records


def build_generation_artifact_manifest(
    records: list[GenerationRecord],
    candidate_config: CandidateConfig,
    tasks: list[EvalTask],
    *,
    suite_id: str,
    suite_version: str,
    content_digest: str,
    scoring_digest: str,
    run_id: str,
    created_at: str,
):
    """Builds the durable, serializable GenerationArtifactManifest from
    a completed generation phase's records -- the artifact that
    actually crosses the trust/machine boundary (Phase 21B.4.8.1 spec
    section 3), not a bare list of GenerationRecords with ephemeral
    paths. Callers running generation and scoring on separate machines
    should serialize this (to_json()) and transfer/persist it, then
    call run_scoring_phase_from_artifact() with the deserialized copy
    on the scoring side."""
    from orca.eval.generation_artifact import GENERATION_ARTIFACT_SCHEMA_VERSION, GenerationArtifactManifest

    task_ids = tuple(t.task_id for t in tasks)
    record_dicts = tuple(
        {
            "task_id": r.task_id, "category": r.category, "scoring_type": r.scoring_type,
            "text_sha256": r.text_sha256, "byte_length": r.byte_length, "error": r.error,
            "latency_ms": r.latency_ms, "raw_response_ref": r.raw_response_ref,
        }
        for r in records
    )
    generation_config_digest = hashlib.sha256(
        json.dumps(candidate_config.inference_config, sort_keys=True).encode("utf-8")
    ).hexdigest()

    return GenerationArtifactManifest(
        schema_version=GENERATION_ARTIFACT_SCHEMA_VERSION,
        run_id=run_id, candidate=candidate_config.candidate,
        upstream_model=candidate_config.upstream_model, artifact_repo=candidate_config.artifact_repo,
        exact_revision=candidate_config.exact_revision, tokenizer_revision=candidate_config.tokenizer_revision,
        suite_id=suite_id, suite_version=suite_version,
        suite_content_digest=content_digest, suite_scoring_contract_digest=scoring_digest,
        generation_config_digest=f"sha256:{generation_config_digest}",
        system_instruction_digest=f"sha256:{_sha256_of_text(candidate_config.system_instruction)}",
        expected_task_ids=task_ids, records=record_dicts,
        software_commit_sha=_current_git_sha(), backend=candidate_config.backend,
        hardware=dict(candidate_config.hardware), created_at=created_at,
    )


def materialize_generation_artifact(
    remote_records: list[RemoteGenerationRecord],
    candidate_config: CandidateConfig,
    tasks: list[EvalTask],
    *,
    suite_id: str,
    suite_version: str,
    content_digest: str,
    scoring_digest: str,
    run_id: str,
    created_at: str,
):
    """THE canonical materialization step (Phase 21B.4.8.2 Blocker 1):
    the ORNEUR orchestrator calls this -- never the generation worker
    itself -- with whatever RemoteGenerationRecords a trusted inference
    worker (e.g. a Modal GPU function) returned. It:

      1. Validates every remote record's task coverage against the
         live-verified suite BEFORE persisting anything
         (_validate_remote_records_against_tasks() -- fails closed on
         missing/duplicate/unknown/category-mismatched records).
      2. Persists each non-error record's raw text into the
         orchestrator's own canonical, content-addressed ORCA_HOME
         store (orca.eval.generation_artifact.persist_raw_response) --
         never trusts or reconstructs a path from the generation
         worker's own filesystem.
      3. Builds and returns the (unsealed) GenerationArtifactManifest
         via build_generation_artifact_manifest() -- the same manifest-
         construction logic run_generation_phase()'s local-mode path
         uses, so there is one manifest-building implementation, not
         two competing ones.

    Callers should then call
    orca.eval.generation_artifact.write_sealed_generation_artifact()
    (or seal_generation_artifact()) to produce the tamper-evident sealed
    bundle before transferring it to a scoring host."""
    from orca.eval.generation_artifact import persist_raw_response

    _validate_remote_records_against_tasks(remote_records, tasks)

    generation_records: list[GenerationRecord] = []
    for rr in remote_records:
        if rr.error is not None or rr.text is None:
            generation_records.append(GenerationRecord(
                task_id=rr.task_id, category=rr.category, scoring_type=rr.scoring_type,
                text=None, error=rr.error or "no text returned", latency_ms=rr.latency_ms, raw_response_ref=None,
            ))
            continue
        raw_ref, digest, length = persist_raw_response(run_id, rr.task_id, rr.text)
        generation_records.append(GenerationRecord(
            task_id=rr.task_id, category=rr.category, scoring_type=rr.scoring_type,
            text=rr.text, error=None, latency_ms=rr.latency_ms, raw_response_ref=raw_ref,
            text_sha256=digest, byte_length=length,
        ))

    return build_generation_artifact_manifest(
        generation_records, candidate_config, tasks,
        suite_id=suite_id, suite_version=suite_version,
        content_digest=content_digest, scoring_digest=scoring_digest,
        run_id=run_id, created_at=created_at,
    )


def run_scoring_phase(
    generation_records: list[GenerationRecord],
    candidate_config: CandidateConfig,
    tasks: list[EvalTask],
    *,
    suite_id: str,
    suite_version: str,
    content_digest: str,
    scoring_digest: str,
    run_id: str,
    started_at: str,
) -> tuple[EvaluationResultManifest, list[str]]:
    """ScoringExecutor: consumes GenerationRecords (from run_generation_phase,
    persisted to disk, or received over any transport) and runs
    orca.eval.genesis_suite.score_task() -- the only place a
    SandboxBackend/Docker is required. This is the half of run_suite()
    that must run on a machine with a qualified SandboxBackend
    available; it never needs a GPU."""
    per_task_results: list[dict] = []
    generation_failures: list[dict] = []
    unscored_categories: set[str] = set()
    scored_task_ids: list[str] = []
    tasks_by_id = {t.task_id: t for t in tasks}

    system_digest = _sha256_of_text(candidate_config.system_instruction)

    for record in generation_records:
        if record.error is not None or record.text is None:
            generation_failures.append({
                "task_id": record.task_id, "category": record.category,
                "reason": record.error or "no text returned", "latency_ms": record.latency_ms,
            })
            continue

        if record.scoring_type == "llm_judge":
            unscored_categories.add(str(record.category))
            per_task_results.append({
                "task_id": record.task_id, "category": record.category, "passed": None,
                "scoring_type": record.scoring_type, "note": CANDIDATE_UNSCORED_MARKER,
                "latency_ms": record.latency_ms, "raw_response_ref": record.raw_response_ref,
            })
            continue

        task = tasks_by_id[record.task_id]
        scorer_output = score_task(task, record.text)
        per_task_results.append({
            "task_id": record.task_id, "category": record.category, "passed": scorer_output.get("passed"),
            "scoring_type": record.scoring_type, "scorer_output": scorer_output,
            "latency_ms": record.latency_ms, "raw_response_ref": record.raw_response_ref,
        })
        scored_task_ids.append(record.task_id)

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
        run_id=run_id,
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


def _score_manifest_common(
    manifest,
    candidate_config: CandidateConfig,
    tasks: list[EvalTask],
    *,
    suite_id: str,
    suite_version: str,
    content_digest: str,
    scoring_digest: str,
    started_at: str,
) -> tuple[EvaluationResultManifest, list[str]]:
    """The ONE security-relevant verification+scoring implementation
    shared by both scoring entry points (Phase 21B.4.8.3 section 7:
    "do not maintain parallel security semantics"). Given a raw
    GenerationArtifactManifest (already unwrapped from a
    VerifiedGenerationArtifact by the real entry point, or passed
    directly by the legacy/harness entry point):

      1. Verifies `manifest`'s IDENTITY against `candidate_config` and
         the suite parameters (orca.eval.generation_artifact
         .verify_manifest_identity()) -- fails closed with
         GenerationArtifactIdentityMismatchError on any mismatch.
      2. Reconciles `manifest` against the live-verified `tasks`
         (orca.eval.generation_artifact.verify_against_suite) -- fails
         closed with GenerationArtifactIntegrityError on any missing/
         duplicate/unknown/category-mismatched record.
      3. Re-reads and verifies (SHA-256 AND byte_length) every non-error
         record's raw response from the durable store before trusting
         its content.

    Only after all three checks pass does it reconstruct
    GenerationRecords and delegate to run_scoring_phase(). Callers of
    THIS function are responsible for deciding what provenance_kind the
    returned result gets stamped with -- this function never stamps
    provenance itself."""
    from orca.eval.generation_artifact import (
        read_and_verify_raw_response,
        verify_against_suite,
        verify_manifest_identity,
    )

    verify_manifest_identity(
        manifest, candidate_config, tasks,
        suite_id=suite_id, suite_version=suite_version,
        content_digest=content_digest, scoring_digest=scoring_digest,
    )
    verify_against_suite(manifest, tasks)

    records: list[GenerationRecord] = []
    for entry in manifest.records:
        if entry.get("error") is not None or entry.get("text_sha256") is None:
            records.append(GenerationRecord(
                task_id=entry["task_id"], category=entry["category"], scoring_type=entry["scoring_type"],
                text=None, error=entry.get("error") or "no text returned", latency_ms=entry.get("latency_ms", 0.0),
                raw_response_ref=None,
            ))
            continue
        verified_text = read_and_verify_raw_response(
            entry["raw_response_ref"], entry["text_sha256"], entry.get("byte_length"),
        )
        records.append(GenerationRecord(
            task_id=entry["task_id"], category=entry["category"], scoring_type=entry["scoring_type"],
            text=verified_text, error=None, latency_ms=entry.get("latency_ms", 0.0),
            raw_response_ref=entry["raw_response_ref"], text_sha256=entry["text_sha256"],
            byte_length=entry.get("byte_length"),
        ))

    return run_scoring_phase(
        records, candidate_config, tasks,
        suite_id=suite_id, suite_version=suite_version,
        content_digest=content_digest, scoring_digest=scoring_digest,
        run_id=manifest.run_id, started_at=started_at,
    )


def score_verified_generation_artifact(
    verified_artifact,
    candidate_config: CandidateConfig,
    tasks: list[EvalTask],
    *,
    suite_id: str,
    suite_version: str,
    content_digest: str,
    scoring_digest: str,
    started_at: str,
) -> tuple[EvaluationResultManifest, list[str]]:
    """THE real-benchmark scoring entry point (Phase 21B.4.8.3). Accepts
    ONLY an orca.eval.generation_artifact.VerifiedGenerationArtifact --
    proof that the exact serialized bytes were checked against an
    independently-retained expected digest BEFORE deserialization
    (produced exclusively by
    orca.eval.generation_artifact.load_and_verify_generation_artifact()).
    A bare/hand-built/merely-deserialized GenerationArtifactManifest is
    rejected outright with TypeError -- it is not accepted here under
    any circumstance, closing the "raw manifest passed directly to real
    scoring" gap an independent audit found.

    Runs the same identity/coverage/raw-response verification as the
    legacy path (_score_manifest_common()) -- there is one security
    implementation, not two -- then AUTOMATICALLY stamps the returned
    EvaluationResultManifest with:

      provenance_kind = "real_generation_artifact"
      generation_artifact_digest = verified_artifact.bundle_digest
      generation_artifact_schema_version = verified_artifact.schema_version

    The caller never manually fills these fields -- closing the "a
    syntactically valid digest string is not provenance" gap: the ONLY
    way to get a result stamped provenance_kind="real_generation_artifact"
    is to go through this function with a genuinely verified artifact."""
    from orca.eval.generation_artifact import VerifiedGenerationArtifact

    if not isinstance(verified_artifact, VerifiedGenerationArtifact):
        raise TypeError(
            f"score_verified_generation_artifact() requires a VerifiedGenerationArtifact, got "
            f"{type(verified_artifact).__name__} instead -- use "
            "orca.eval.generation_artifact.load_and_verify_generation_artifact() to produce one. "
            "A bare GenerationArtifactManifest is never accepted by the real scoring entry point."
        )

    result, scored_task_ids = _score_manifest_common(
        verified_artifact.manifest, candidate_config, tasks,
        suite_id=suite_id, suite_version=suite_version,
        content_digest=content_digest, scoring_digest=scoring_digest, started_at=started_at,
    )
    result.provenance_kind = "real_generation_artifact"
    result.generation_artifact_digest = verified_artifact.bundle_digest
    result.generation_artifact_schema_version = verified_artifact.schema_version
    return result, scored_task_ids


def run_scoring_phase_from_artifact(
    manifest,
    candidate_config: CandidateConfig,
    tasks: list[EvalTask],
    *,
    suite_id: str,
    suite_version: str,
    content_digest: str,
    scoring_digest: str,
    started_at: str,
) -> tuple[EvaluationResultManifest, list[str]]:
    """LEGACY/harness-only entry point (Phase 21B.4.8.1, restricted in
    Phase 21B.4.8.3). Accepts a raw (unsealed) GenerationArtifactManifest
    directly and runs the EXACT same identity/coverage/raw-response
    verification as the real path (_score_manifest_common() -- there is
    no security downgrade for those checks), but the returned result is
    ALWAYS stamped provenance_kind="synthetic_test" (never
    "real_generation_artifact"), regardless of what the input manifest
    claims -- nothing here proves the manifest's bytes were ever checked
    against an independently-retained digest, so it can never be trusted
    as a real baseline.
    orca.eval.baseline.record_baseline_and_freeze_suite() unconditionally
    rejects any non-"real_generation_artifact" provenance_kind, so a
    result from this function can never freeze genesis-eval-v1.

    Existing tests and harness-validation callers may keep using this
    entry point; a REAL cross-machine evaluation MUST use
    score_verified_generation_artifact() instead."""
    result, scored_task_ids = _score_manifest_common(
        manifest, candidate_config, tasks,
        suite_id=suite_id, suite_version=suite_version,
        content_digest=content_digest, scoring_digest=scoring_digest, started_at=started_at,
    )
    result.provenance_kind = "synthetic_test"
    result.generation_artifact_digest = None
    result.generation_artifact_schema_version = None
    return result, scored_task_ids


def run_suite(
    adapter: ModelAdapter,
    candidate_config: CandidateConfig,
    *,
    suite_id: str = "genesis-eval",
    suite_version: str = "v1",
    run_id: str | None = None,
) -> tuple[EvaluationResultManifest, list[str]]:
    """Local/same-machine HARNESS path -- NOT the real-benchmark path
    (Phase 21B.4.8.3 section 8). Executes EVERY task in the persisted,
    verified suite against `adapter`, producing a NOT-yet-finalized
    EvaluationResultManifest ALWAYS stamped provenance_kind=
    "synthetic_test" (regardless of which ModelAdapter is used, including
    a real one) -- run_suite() never goes through the sealed-artifact
    materialize/seal/verify pipeline, so nothing here proves any
    provenance, and orca.eval.baseline.record_baseline_and_freeze_suite()
    will always reject its output. A REAL frontier-candidate baseline
    MUST use the canonical pipeline instead: run_remote_generation_phase()
    (or run_generation_phase() locally) -> materialize_generation_artifact()
    -> write_sealed_generation_artifact() -> transfer -> read_sealed_
    generation_artifact() + load_and_verify_generation_artifact() ->
    score_verified_generation_artifact(). There is no easier real-
    evaluation path that bypasses provenance -- run_suite() exists solely
    for local harness/dry-run validation of the runner's own plumbing
    (denominator integrity, failure capture, digest wiring).

    Returns (result, scored_task_ids) -- scored_task_ids excludes
    llm_judge tasks, matching record_baseline_and_freeze_suite()'s
    completeness-check contract.

    Implemented as run_generation_phase() + run_scoring_phase() composed
    on a single machine (Phase 21B.4.8 spec section 3)."""
    tasks, suite_manifest = load_and_verify_suite(suite_id, suite_version)
    task_ids, content_digest, scoring_digest = compute_suite_digests(tasks)

    resolved_run_id = run_id or f"run-{uuid.uuid4().hex[:16]}"
    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    generation_records = run_generation_phase(adapter, candidate_config, tasks, run_id=resolved_run_id)

    result, scored_task_ids = run_scoring_phase(
        generation_records, candidate_config, tasks,
        suite_id=suite_id, suite_version=suite_version,
        content_digest=content_digest, scoring_digest=scoring_digest,
        run_id=resolved_run_id, started_at=started_at,
    )
    result.provenance_kind = "synthetic_test"
    result.generation_artifact_digest = None
    result.generation_artifact_schema_version = None
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
