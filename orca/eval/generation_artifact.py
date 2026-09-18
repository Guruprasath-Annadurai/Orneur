"""
GenerationArtifactManifest (Phase 21B.4.8.1) -- the durable, integrity-
verifiable bundle a generation run produces, closing the gap an
independent audit found in Phase 21B.4.8's generation/scoring split:
`GenerationRecord.raw_response_ref` was an ephemeral local filesystem
path with no claim to cross-machine durability, and nothing verified
that every expected suite task actually arrived before scoring ran a
completeness check against whatever records happened to show up.

Two closed gaps, specifically:

1. DURABILITY: if generation runs on a Modal GPU worker and scoring
   runs on a separate Docker-equipped machine, a raw-response path
   created inside the GPU worker's filesystem is not automatically
   readable from anywhere else. `persist_raw_response()` below writes
   into ORCA_HOME's canonical evaluation-artifact tree (content-
   addressed by SHA-256), which is what the ORCHESTRATOR must do with
   whatever text a GPU worker returns to it -- BEFORE handing anything
   to scoring, not merely trusting a path string from the GPU
   environment. `GenerationArtifactManifest` records each response's
   SHA-256 and byte length so a scorer can independently verify the
   bytes it reads back are exactly what generation produced, not
   silently truncated/corrupted/substituted in transit.

2. DENOMINATOR INTEGRITY: `run_scoring_phase()` (orca.eval.runner)
   previously iterated over whatever GenerationRecords it was handed,
   with no independent check that the set it received actually matches
   the verified suite's task set. A record dropped in cross-machine
   transfer would simply be absent from scoring, and the LATER
   completeness check (orca.eval.baseline) used the scoring phase's
   own observed output as its definition of "what was expected" --
   an observed subset validating itself. `verify_against_suite()`
   below is the fail-closed fix: it derives "what was expected" ONLY
   from the live-verified suite task list, and refuses (raises
   GenerationArtifactIntegrityError) if any expected task is missing,
   any unknown task_id is present, any task_id is duplicated, or any
   record's category/scoring_type disagrees with what the suite itself
   says for that task_id. This runs BEFORE scoring, never after.

Missing transport data is explicitly NOT a generation failure (which
means "the model was asked and failed to answer") -- it is an
integrity error (which means "we don't actually know what happened to
this task's data"), and the two must never be conflated.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from orca.config import ORCA_HOME

GENERATION_ARTIFACT_SCHEMA_VERSION = "genesis-generation-v1"

GENERATION_ARTIFACT_DIR = ORCA_HOME / "registry" / "evaluation_generation_artifacts"
GENERATION_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


class GenerationArtifactIntegrityError(Exception):
    """Raised when a GenerationArtifactManifest's records do not
    reconcile against the live-verified suite task set -- missing
    task, unknown task, duplicate task_id, or a category/scoring_type
    mismatch. This is a transport/integrity failure, never silently
    treated as a generation failure or silently ignored. Scoring must
    not proceed past this error."""


def _sha256_of_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def persist_raw_response(run_id: str, task_id: str, text: str) -> tuple[str, str, int]:
    """Writes `text` into ORCA_HOME's canonical, durable evaluation-
    artifact tree, content-addressed by SHA-256. Returns
    (raw_response_ref, sha256_hex, byte_length). This is what an
    ORCHESTRATOR calls with text a GPU worker returned to it -- the
    canonical store lives on the orchestrator's own ORCA_HOME, not on
    whatever ephemeral filesystem the GPU worker had."""
    encoded = text.encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    run_dir = GENERATION_ARTIFACT_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / f"{task_id}-{digest[:16]}.txt"
    path.write_text(text)
    return str(path), digest, len(encoded)


def read_and_verify_raw_response(raw_response_ref: str, expected_sha256: str) -> str:
    """Reads back a persisted raw response and verifies its SHA-256
    matches what the GenerationArtifactManifest recorded at generation
    time -- detects truncation/corruption/substitution in transit or
    storage. Raises GenerationArtifactIntegrityError on any mismatch or
    missing file, never silently returns unverified content."""
    from pathlib import Path

    path = Path(raw_response_ref)
    if not path.exists():
        raise GenerationArtifactIntegrityError(
            f"raw_response_ref {raw_response_ref!r} does not resolve to an existing file -- "
            "cannot verify or score this task's response."
        )
    text = path.read_text()
    actual = _sha256_of_text(text)
    if actual != expected_sha256:
        raise GenerationArtifactIntegrityError(
            f"raw_response_ref {raw_response_ref!r} content SHA-256 ({actual}) does not match the "
            f"GenerationArtifactManifest's recorded hash ({expected_sha256}) -- response was "
            "corrupted, truncated, or substituted in transit."
        )
    return text


@dataclass(frozen=True)
class GenerationArtifactManifest:
    schema_version: str
    run_id: str
    candidate: str
    upstream_model: str
    artifact_repo: str
    exact_revision: str
    tokenizer_revision: str | None
    suite_id: str
    suite_version: str
    suite_content_digest: str
    suite_scoring_contract_digest: str
    generation_config_digest: str
    system_instruction_digest: str
    expected_task_ids: tuple[str, ...]
    records: tuple[dict, ...]  # one per task: task_id, category, scoring_type, text_sha256|None, byte_length|None, error|None, latency_ms, raw_response_ref|None
    software_commit_sha: str
    backend: str
    hardware: dict = field(default_factory=dict)
    created_at: str = ""

    def bundle_digest(self) -> str:
        """SHA-256 over the canonical JSON serialization -- integrity
        digest for the whole bundle, independent of any single
        record's own hash."""
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    def to_json(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "candidate": self.candidate,
            "upstream_model": self.upstream_model,
            "artifact_repo": self.artifact_repo,
            "exact_revision": self.exact_revision,
            "tokenizer_revision": self.tokenizer_revision,
            "suite_id": self.suite_id,
            "suite_version": self.suite_version,
            "suite_content_digest": self.suite_content_digest,
            "suite_scoring_contract_digest": self.suite_scoring_contract_digest,
            "generation_config_digest": self.generation_config_digest,
            "system_instruction_digest": self.system_instruction_digest,
            "expected_task_ids": list(self.expected_task_ids),
            "records": list(self.records),
            "software_commit_sha": self.software_commit_sha,
            "backend": self.backend,
            "hardware": self.hardware,
            "created_at": self.created_at,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, raw: str) -> "GenerationArtifactManifest":
        data = json.loads(raw)
        if data.get("schema_version") != GENERATION_ARTIFACT_SCHEMA_VERSION:
            raise GenerationArtifactIntegrityError(
                f"Unsupported GenerationArtifactManifest schema_version={data.get('schema_version')!r} "
                f"(expected {GENERATION_ARTIFACT_SCHEMA_VERSION!r})"
            )
        return cls(
            schema_version=data["schema_version"], run_id=data["run_id"], candidate=data["candidate"],
            upstream_model=data["upstream_model"], artifact_repo=data["artifact_repo"],
            exact_revision=data["exact_revision"], tokenizer_revision=data.get("tokenizer_revision"),
            suite_id=data["suite_id"], suite_version=data["suite_version"],
            suite_content_digest=data["suite_content_digest"],
            suite_scoring_contract_digest=data["suite_scoring_contract_digest"],
            generation_config_digest=data["generation_config_digest"],
            system_instruction_digest=data["system_instruction_digest"],
            expected_task_ids=tuple(data["expected_task_ids"]), records=tuple(data["records"]),
            software_commit_sha=data["software_commit_sha"], backend=data["backend"],
            hardware=data.get("hardware", {}), created_at=data.get("created_at", ""),
        )


def verify_against_suite(manifest: GenerationArtifactManifest, tasks: list) -> None:
    """The fail-closed reconciliation (spec section 6-7): 'expected'
    comes ONLY from `tasks` (the live-verified suite), never from the
    manifest's own `expected_task_ids` field (which the manifest itself
    claims, and therefore cannot be trusted to define its own
    correctness) and never from whichever records happen to be present.
    Raises GenerationArtifactIntegrityError before any scoring may
    occur if:
      - any suite task_id has zero records,
      - any suite task_id has more than one record (duplicate),
      - any record's task_id is not in the suite at all (unknown),
      - any record's category or scoring_type disagrees with the
        suite's own definition for that task_id.
    """
    suite_by_id = {t.task_id: t for t in tasks}
    suite_task_ids = set(suite_by_id.keys())

    seen: dict[str, int] = {}
    unknown: list[str] = []
    mismatched: list[str] = []
    for record in manifest.records:
        tid = record.get("task_id")
        seen[tid] = seen.get(tid, 0) + 1
        if tid not in suite_by_id:
            unknown.append(tid)
            continue
        suite_task = suite_by_id[tid]
        if record.get("category") != suite_task.category or record.get("scoring_type") != suite_task.scoring_type:
            mismatched.append(tid)

    duplicates = sorted(tid for tid, count in seen.items() if count > 1)
    missing = sorted(suite_task_ids - set(seen.keys()))

    problems = []
    if missing:
        problems.append(f"missing {len(missing)} expected task(s): {missing[:10]}{'...' if len(missing) > 10 else ''}")
    if duplicates:
        problems.append(f"{len(duplicates)} duplicate task_id(s): {duplicates[:10]}{'...' if len(duplicates) > 10 else ''}")
    if unknown:
        problems.append(f"{len(unknown)} unknown task_id(s) not in the suite: {sorted(set(unknown))[:10]}")
    if mismatched:
        problems.append(f"{len(mismatched)} task(s) with category/scoring_type mismatched against the suite: {sorted(mismatched)[:10]}")

    if problems:
        raise GenerationArtifactIntegrityError(
            f"GenerationArtifactManifest for run_id={manifest.run_id!r} failed reconciliation against "
            f"the verified suite ({manifest.suite_id}-{manifest.suite_version}): " + "; ".join(problems)
        )
