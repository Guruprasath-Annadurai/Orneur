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

Phase 21B.4.8.2 closes three further provenance gaps an independent
audit found in this module's first version:

3. SEALING: `bundle_digest()` alone is not a verified transfer
   invariant -- `from_json()` happily deserializes ANY well-formed JSON,
   including a tampered bundle with a freshly recomputed digest sitting
   inside the same mutable blob. `seal_generation_artifact()` /
   `write_sealed_generation_artifact()` produce the canonical bytes and
   digest as two SEPARATE artifacts (a `.json` file and a sibling
   `.sha256` file); `load_and_verify_generation_artifact()` requires the
   expected digest to be supplied independently (never read out of the
   same blob it is verifying) and hashes the exact received bytes BEFORE
   any deserialization is attempted.

4. IDENTITY BINDING: `verify_against_suite()` checks task coverage, but
   never checked that the manifest was actually generated FOR the
   candidate/revision/suite/config that scoring is about to score it
   against. `verify_manifest_identity()` closes this: candidate,
   upstream_model, artifact_repo, exact_revision, tokenizer_revision,
   backend, suite_id/version/digests, generation_config_digest,
   system_instruction_digest, and expected_task_ids are all checked
   against independently-derived values before scoring may proceed.

5. BYTE-EXACT RAW-RESPONSE STORAGE: `persist_raw_response()`/
   `read_and_verify_raw_response()` now write/read raw bytes
   (`write_bytes`/`read_bytes`, atomically) rather than locale-dependent
   text I/O, and verify BOTH `byte_length` and SHA-256 on read -- the
   hash remains authoritative, but a byte_length mismatch is now also
   independently detected and reported.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from orca.config import ORCA_HOME

GENERATION_ARTIFACT_SCHEMA_VERSION = "genesis-generation-v1"

GENERATION_ARTIFACT_DIR = ORCA_HOME / "registry" / "evaluation_generation_artifacts"
GENERATION_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

# Phase 21B.4.8.2: where SEALED (bundle-bytes + separately-retained
# digest) generation artifacts live -- deliberately a different
# directory from GENERATION_ARTIFACT_DIR (per-task raw-response text)
# above, since these are whole-manifest bundles, not individual
# responses.
GENERATION_ARTIFACT_MANIFEST_DIR = ORCA_HOME / "registry" / "evaluation_generation_artifact_manifests"
GENERATION_ARTIFACT_MANIFEST_DIR.mkdir(parents=True, exist_ok=True)


class GenerationArtifactIntegrityError(Exception):
    """Raised when a GenerationArtifactManifest's records do not
    reconcile against the live-verified suite task set -- missing
    task, unknown task, duplicate task_id, or a category/scoring_type
    mismatch. This is a transport/integrity failure, never silently
    treated as a generation failure or silently ignored. Scoring must
    not proceed past this error."""


class GenerationArtifactIdentityMismatchError(GenerationArtifactIntegrityError):
    """A GenerationArtifactManifest's identity fields (candidate, exact
    revision, tokenizer revision, artifact repo, backend, suite
    identity/digests, generation-config digest, system-instruction
    digest, or expected_task_ids) do not match the scoring-side
    CandidateConfig/suite it is being scored against -- e.g. generation
    ran candidate A but scoring is being attempted with candidate B's
    CandidateConfig. Raised BEFORE any scoring occurs; the manifest's
    identity is never silently rewritten to match the caller's
    CandidateConfig (Phase 21B.4.8.2 Blocker 2)."""


def _sha256_of_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Writes `data` to `path` atomically: temp file in the same
    directory -> flush -> fsync -> os.replace(). A crash or concurrent
    reader can never observe a partially-written file at `path` (spec:
    'Writes should be atomic. Prefer: temporary file -> fsync where
    reasonable -> atomic replace')."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def persist_raw_response(run_id: str, task_id: str, text: str) -> tuple[str, str, int]:
    """Writes `text` into ORCA_HOME's canonical, durable evaluation-
    artifact tree, content-addressed by SHA-256, using exact UTF-8 bytes
    (not locale-dependent text I/O) written atomically. Returns
    (raw_response_ref, sha256_hex, byte_length). This is what an
    ORCHESTRATOR calls with text a GPU worker returned to it -- the
    canonical store lives on the orchestrator's own ORCA_HOME, not on
    whatever ephemeral filesystem the GPU worker had."""
    encoded = text.encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    run_dir = GENERATION_ARTIFACT_DIR / run_id
    path = run_dir / f"{task_id}-{digest[:16]}.txt"
    _atomic_write_bytes(path, encoded)
    return str(path), digest, len(encoded)


def read_and_verify_raw_response(
    raw_response_ref: str, expected_sha256: str, expected_byte_length: int | None = None,
) -> str:
    """Reads back a persisted raw response (exact bytes, then UTF-8
    decoded) and verifies its SHA-256 -- and, when `expected_byte_length`
    is supplied, its byte length too -- match what the
    GenerationArtifactManifest recorded at generation time. Detects
    truncation/corruption/substitution in transit or storage. The hash
    remains authoritative (a byte_length match alone is not sufficient
    evidence), but a byte_length mismatch is independently reported
    rather than only surfacing as a hash mismatch. Raises
    GenerationArtifactIntegrityError on any mismatch or missing file,
    never silently returns unverified content."""
    path = Path(raw_response_ref)
    if not path.exists():
        raise GenerationArtifactIntegrityError(
            f"raw_response_ref {raw_response_ref!r} does not resolve to an existing file -- "
            "cannot verify or score this task's response."
        )
    encoded = path.read_bytes()
    if expected_byte_length is not None and len(encoded) != expected_byte_length:
        raise GenerationArtifactIntegrityError(
            f"raw_response_ref {raw_response_ref!r} byte_length ({len(encoded)}) does not match the "
            f"GenerationArtifactManifest's recorded byte_length ({expected_byte_length}) -- response was "
            "truncated or altered in transit."
        )
    actual = hashlib.sha256(encoded).hexdigest()
    if actual != expected_sha256:
        raise GenerationArtifactIntegrityError(
            f"raw_response_ref {raw_response_ref!r} content SHA-256 ({actual}) does not match the "
            f"GenerationArtifactManifest's recorded hash ({expected_sha256}) -- response was "
            "corrupted, truncated, or substituted in transit."
        )
    return encoded.decode("utf-8")


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


def verify_manifest_identity(
    manifest: GenerationArtifactManifest,
    candidate_config,
    tasks: list,
    *,
    suite_id: str,
    suite_version: str,
    content_digest: str,
    scoring_digest: str,
) -> None:
    """Phase 21B.4.8.2 Blocker 2: checks that `manifest` was actually
    generated FOR the exact candidate/revision/suite/config combination
    scoring is about to score it against -- `verify_against_suite()`
    checks task coverage, but says nothing about whether the manifest
    belongs to a different candidate, a different pinned revision, a
    different system instruction, or a different suite version. Every
    identity field is checked against an INDEPENDENTLY derived expected
    value (never against another field pulled from the same manifest),
    and `expected_task_ids` is compared as an ordered tuple against the
    live-verified suite's own task order -- never trusting the
    manifest's own list as ground truth, but still rejecting the
    artifact outright if its claimed list disagrees with truth.

    Raises GenerationArtifactIdentityMismatchError (a
    GenerationArtifactIntegrityError subclass) on ANY mismatch, before
    verify_against_suite() or any scoring runs. The manifest's identity
    is never rewritten to match candidate_config -- a mismatch is always
    a hard failure, never a silent reconciliation."""
    expected_generation_config_digest = "sha256:" + hashlib.sha256(
        json.dumps(candidate_config.inference_config, sort_keys=True).encode("utf-8")
    ).hexdigest()
    expected_system_instruction_digest = "sha256:" + _sha256_of_text(candidate_config.system_instruction)
    expected_task_ids = tuple(t.task_id for t in tasks)

    checks = [
        ("candidate", manifest.candidate, candidate_config.candidate),
        ("upstream_model", manifest.upstream_model, candidate_config.upstream_model),
        ("artifact_repo", manifest.artifact_repo, candidate_config.artifact_repo),
        ("exact_revision", manifest.exact_revision, candidate_config.exact_revision),
        ("tokenizer_revision", manifest.tokenizer_revision, candidate_config.tokenizer_revision),
        ("backend", manifest.backend, candidate_config.backend),
        ("suite_id", manifest.suite_id, suite_id),
        ("suite_version", manifest.suite_version, suite_version),
        ("suite_content_digest", manifest.suite_content_digest, content_digest),
        ("suite_scoring_contract_digest", manifest.suite_scoring_contract_digest, scoring_digest),
        ("generation_config_digest", manifest.generation_config_digest, expected_generation_config_digest),
        ("system_instruction_digest", manifest.system_instruction_digest, expected_system_instruction_digest),
        ("expected_task_ids", manifest.expected_task_ids, expected_task_ids),
    ]
    mismatches = [(name, got, want) for name, got, want in checks if got != want]
    if mismatches:
        details = "; ".join(f"{name}: manifest={got!r} != expected={want!r}" for name, got, want in mismatches)
        raise GenerationArtifactIdentityMismatchError(
            f"GenerationArtifactManifest run_id={manifest.run_id!r} identity does not match the scoring "
            f"request -- refusing to score outputs generated for a different candidate/revision/config/"
            f"suite than the one currently being requested: {details}"
        )


# ── sealing / tamper-evident transfer (Phase 21B.4.8.2 Blocker 3) ───────


def seal_generation_artifact(manifest: GenerationArtifactManifest) -> tuple[bytes, str]:
    """Produces the canonical serialized bytes and their SHA-256 digest
    -- the two values a caller must retain SEPARATELY (never re-deriving
    the digest from the same blob it is meant to verify) before
    transferring the bundle anywhere. Returns (serialized_bytes,
    bundle_sha256_hex)."""
    serialized = manifest.to_json().encode("utf-8")
    digest = hashlib.sha256(serialized).hexdigest()
    return serialized, digest


def write_sealed_generation_artifact(manifest: GenerationArtifactManifest) -> tuple[Path, Path, str]:
    """Atomically persists a sealed generation artifact as TWO separate
    files under the canonical ORCA_HOME store: `<run_id>.json` (the
    bundle bytes) and `<run_id>.sha256` (the digest, as a trusted
    orchestration record retained independently of the JSON blob it
    verifies). Returns (json_path, digest_path, bundle_sha256_hex)."""
    serialized, digest = seal_generation_artifact(manifest)
    json_path = GENERATION_ARTIFACT_MANIFEST_DIR / f"{manifest.run_id}.json"
    digest_path = GENERATION_ARTIFACT_MANIFEST_DIR / f"{manifest.run_id}.sha256"
    _atomic_write_bytes(json_path, serialized)
    _atomic_write_bytes(digest_path, digest.encode("ascii"))
    return json_path, digest_path, digest


def read_sealed_generation_artifact(run_id: str) -> tuple[bytes, str]:
    """Reads back the two separately-persisted files
    write_sealed_generation_artifact() wrote for `run_id`. Returns
    (serialized_bytes, expected_digest) -- pass both to
    load_and_verify_generation_artifact(). Raises
    GenerationArtifactIntegrityError if either file is missing (a
    dropped digest file is exactly as much an integrity failure as a
    dropped bundle file -- there is no meaningful 'load without
    verification' path)."""
    json_path = GENERATION_ARTIFACT_MANIFEST_DIR / f"{run_id}.json"
    digest_path = GENERATION_ARTIFACT_MANIFEST_DIR / f"{run_id}.sha256"
    if not json_path.exists() or not digest_path.exists():
        raise GenerationArtifactIntegrityError(
            f"Sealed generation artifact for run_id={run_id!r} is incomplete -- "
            f"json_exists={json_path.exists()}, digest_exists={digest_path.exists()}."
        )
    serialized = json_path.read_bytes()
    expected_digest = digest_path.read_bytes().decode("ascii").strip()
    return serialized, expected_digest


def load_and_verify_generation_artifact(serialized: bytes, expected_digest: str) -> GenerationArtifactManifest:
    """The verified-load half of the seal/verify flow (Phase 21B.4.8.2
    Blocker 3). `expected_digest` MUST come from a trusted orchestration
    record or a separately-retained value (e.g.
    read_sealed_generation_artifact()'s digest_path, or a value a caller
    persisted independently at seal time) -- never from a digest field
    read out of `serialized` itself, which would let a tampered bundle
    simply carry its own freshly recomputed digest.

    Order of operations, exactly as required:
      1. hash the received exact bytes;
      2. compare against expected_digest;
      3. fail closed (GenerationArtifactIntegrityError) on mismatch;
      4. only then deserialize (from_json(), which also validates the
         schema_version);
      5. semantic identity (candidate/revision/suite/config) and
         6. raw-response hashes are validated separately by
         verify_manifest_identity() / read_and_verify_raw_response(),
         called from run_scoring_phase_from_artifact() -- this function's
         job ends at 'the bytes are exactly what was sealed, and the
         schema is one we understand'."""
    actual_digest = hashlib.sha256(serialized).hexdigest()
    if actual_digest != expected_digest:
        raise GenerationArtifactIntegrityError(
            f"Sealed generation artifact bundle digest mismatch: expected {expected_digest}, got "
            f"{actual_digest} -- the bundle was tampered with, truncated, or corrupted in transit. "
            "Refusing to deserialize an unverified bundle."
        )
    return GenerationArtifactManifest.from_json(serialized.decode("utf-8"))
