"""
Checkpoint lifecycle abstraction. Before this module, checkpoint identity
was "whatever the filename says" (see docs/orneur/phase-0/MODEL_TRAINING_STATUS.md:
"no adapter naming registry or 'latest' pointer file was found anywhere in
code... history is tracked only via notebook filenames"). This gives every
checkpoint a real identity record with checksum-verifiable integrity.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from orca.config import ORCA_HOME
from orca.registry._ids import validate_id
from orca.registry.dataset_manifest import sha256_of_file

CHECKPOINT_DIR = ORCA_HOME / "registry" / "checkpoints"
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)


class CorruptCheckpointError(Exception):
    pass


class CheckpointStructureInvalid(ValueError):
    """A checkpoint artifact directory is structurally incomplete or
    unsafe -- Phase 21B.2: a deterministic digest of whatever files
    happen to be present (hash_artifact_directory()) proves identity,
    never structural completeness. A checkpoint missing its tokenizer,
    config, or a shard referenced by its own index must never be
    registered merely because it hashes cleanly."""


# A merged HF/safetensors checkpoint's required tokenizer artifact may
# be named any of these depending on tokenizer type -- at least one
# must be present.
_TOKENIZER_CANDIDATE_FILES = frozenset({"tokenizer.json", "tokenizer.model", "tokenizer_config.json"})
_SHARD_INDEX_FILES = frozenset({"model.safetensors.index.json", "pytorch_model.bin.index.json"})
_SINGLE_WEIGHT_FILE_CANDIDATES = frozenset({"model.safetensors", "pytorch_model.bin"})


@dataclass(frozen=True)
class CheckpointValidationResult:
    valid: bool
    files_validated: tuple[str, ...]


def validate_checkpoint_artifact(path: Path) -> CheckpointValidationResult:
    """Structural completeness check, run BEFORE a checkpoint is hashed
    and registered (see orca.registry.provenance.complete_training_run()).
    Raises CheckpointStructureInvalid (never a raw exception) for any of:
    missing/unparseable config.json, missing tokenizer artifact, no
    weight file/shard-index found, a shard-index referencing a file that
    doesn't exist or that escapes the artifact root (path traversal),
    or a malformed index. Returns the set of files this validator
    actually inspected and accepted on success -- callers may use this
    to cross-check against hash_artifact_directory()'s own file list,
    but this function does not itself compute any digest (identity and
    validity are deliberately separate concerns)."""
    if not path.exists():
        raise CheckpointStructureInvalid(f"Artifact directory does not exist: {path}")
    if not path.is_dir():
        raise CheckpointStructureInvalid(f"Artifact path is not a directory: {path}")

    # Phase 21B.2.1 (§10-11): fail-closed symlink policy -- a canonical
    # checkpoint must never gain trusted content by symlink escape outside
    # its artifact root. Path.is_file() follows symlinks, so a symlinked
    # config.json/tokenizer.json/weight file would otherwise be silently
    # accepted as trusted content regardless of where it actually points.
    # Rather than resolve-and-compare per required file (duplicating the
    # shard-index escape check below), the simpler fail-closed policy is
    # applied uniformly: ANY symlink directly in the artifact directory
    # -- required or not -- rejects the whole checkpoint. This also keeps
    # the validator and hash_artifact_directory() (which applies the same
    # policy -- see its docstring) from ever disagreeing about which
    # bytes belong to the checkpoint.
    symlink_names = {p.name for p in path.iterdir() if p.is_symlink()}
    if symlink_names:
        raise CheckpointStructureInvalid(
            f"Artifact directory contains symlink(s), which are never trusted checkpoint "
            f"content (fail-closed symlink policy): {sorted(symlink_names)}"
        )

    entries = {p.name for p in path.iterdir() if p.is_file()}

    if "config.json" not in entries:
        raise CheckpointStructureInvalid("Missing required config.json")
    try:
        json.loads((path / "config.json").read_text())
    except json.JSONDecodeError as exc:
        raise CheckpointStructureInvalid(f"config.json does not parse as JSON: {exc}") from exc

    tokenizer_files = entries & _TOKENIZER_CANDIDATE_FILES
    if not tokenizer_files:
        raise CheckpointStructureInvalid(
            f"Missing required tokenizer artifact -- expected at least one of {sorted(_TOKENIZER_CANDIDATE_FILES)}"
        )

    validated: set[str] = {"config.json"} | tokenizer_files

    index_files = entries & _SHARD_INDEX_FILES
    if index_files:
        for index_name in sorted(index_files):
            try:
                index_data = json.loads((path / index_name).read_text())
            except json.JSONDecodeError as exc:
                raise CheckpointStructureInvalid(f"{index_name} does not parse as JSON: {exc}") from exc
            weight_map = index_data.get("weight_map")
            if not isinstance(weight_map, dict) or not weight_map:
                raise CheckpointStructureInvalid(f"{index_name} has no (or a malformed) weight_map")

            referenced_shards = set(weight_map.values())
            resolved_root = path.resolve()
            for shard in referenced_shards:
                if not isinstance(shard, str) or "/" in shard or "\\" in shard or ".." in shard:
                    raise CheckpointStructureInvalid(
                        f"{index_name} references an unsafe shard path (must be a bare filename): {shard!r}"
                    )
                shard_resolved = (path / shard).resolve()
                if shard_resolved.parent != resolved_root:
                    raise CheckpointStructureInvalid(
                        f"{index_name} references a shard path escaping the artifact root: {shard!r}"
                    )
                if shard not in entries:
                    raise CheckpointStructureInvalid(f"{index_name} references a missing shard file: {shard!r}")
            validated.add(index_name)
            validated |= referenced_shards
    else:
        weight_files = entries & _SINGLE_WEIGHT_FILE_CANDIDATES
        if not weight_files:
            raise CheckpointStructureInvalid(
                f"No weight file or shard index found -- expected one of {sorted(_SINGLE_WEIGHT_FILE_CANDIDATES)} "
                f"or one of {sorted(_SHARD_INDEX_FILES)}"
            )
        validated |= weight_files

    return CheckpointValidationResult(valid=True, files_validated=tuple(sorted(validated)))


def hash_artifact_directory(path: Path) -> dict:
    """Deterministic, multi-file checkpoint-artifact IDENTITY (distinct
    from VALIDITY -- see validate_checkpoint_artifact() above, always
    called before this in orca.registry.provenance.complete_training_run()).
    Enumerates every file under `path` (sorted by relative path for
    determinism -- never filesystem traversal order, never mtimes),
    records {path, size, sha256} for each, then hashes the canonical
    JSON of that file list. Changing ANY required file's content, adding
    a file, or removing a file changes the resulting `manifest_digest`.

    Phase 21B.2.1 (§8): this is now THE single canonical directory-
    checkpoint digest algorithm -- previously defined only in
    orca.registry.provenance (which used it for registration) while
    CheckpointRecord.verify_integrity() (post-registration reverification)
    called sha256_of_file() on the same directory path, which is not even
    a valid operation on a directory and silently disagreed with the
    registration-time algorithm for every directory-backed checkpoint.
    Living here (the dependency layer both orca.registry.provenance and
    CheckpointRecord.verify_integrity() already depend on) means both
    call this exact function -- no duplicated hashing logic, and no way
    for registration and reverification to compute different digests for
    the same bytes. orca.registry.provenance re-exports this name via a
    plain import for backward-compatible call sites.

    Applies the same fail-closed symlink policy as
    validate_checkpoint_artifact() -- a symlinked file must never
    silently contribute its target's bytes to a checkpoint's identity
    digest, whether or not validate_checkpoint_artifact() happened to run
    first. This is what makes it safe for the validator and the hasher to
    never disagree about which bytes belong to the checkpoint (§11)."""
    if not path.exists():
        raise FileNotFoundError(f"Artifact directory does not exist: {path}")
    files = []
    for file_path in sorted(p for p in path.rglob("*") if p.is_file()):
        if file_path.is_symlink():
            raise CheckpointStructureInvalid(
                f"Artifact directory contains a symlink, which is never trusted checkpoint "
                f"content (fail-closed symlink policy): {file_path.relative_to(path).as_posix()}"
            )
        rel = file_path.relative_to(path).as_posix()
        files.append({"path": rel, "size": file_path.stat().st_size, "sha256": sha256_of_file(file_path)})
    canonical_json = json.dumps(files, sort_keys=True, separators=(",", ":"))
    manifest_digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    return {"files": files, "manifest_digest": manifest_digest}


class ArtifactAvailability(str, Enum):
    """
    Distinct from LifecycleState (orca/registry/model_spec.py) -- lifecycle
    is about whether a checkpoint is production-worthy; availability is
    about whether its WEIGHT FILE can currently be read at all. A checkpoint
    can be RETIRED (lifecycle) yet still LOCAL (availability), or
    EXPERIMENTAL (lifecycle) yet MISSING (availability) -- the two axes are
    independent. This distinction exists specifically because Phase 1
    overloaded "the artifact isn't reachable" into an ad-hoc checksum
    sentinel string, which this replaces with a real, checked field.
    """
    LOCAL = "LOCAL"          # weight file verified present & readable on this machine
    REMOTE = "REMOTE"        # not local, but verified recoverable from a known source (e.g. a specific Kaggle kernel)
    MISSING = "MISSING"      # not local, no verified recovery path -- the honest "just gone" state
    CORRUPT = "CORRUPT"      # present but fails checksum verification
    ARCHIVED = "ARCHIVED"    # deliberately moved to cold storage, not an accident


@dataclass
class CheckpointRecord:
    checkpoint_id: str            # e.g. "orca-core-combined-v2" -- keeps the legacy name as identity, not a rename
    model_id: str                  # canonical family, e.g. "orneur-novus"
    run_id: str                    # the training run that produced it
    step_or_epoch: str
    base_model: str
    dataset_manifest_ids: list[str]
    training_config_summary: str
    optimizer_state_available: bool
    scheduler_state_available: bool
    tokenizer_identity: str
    artifact_path: str              # where the actual weights/GGUF live (may be a remote/local path)
    artifact_checksum: str          # sha256 of the artifact at save time
    lineage_parent: str | None = None   # parent checkpoint_id, if this one resumed/derived from another
    legacy_ollama_name: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    validation_state: str = "UNVALIDATED"  # UNVALIDATED | VALID | CORRUPT
    # Deliberately defaults to MISSING, not LOCAL -- a checkpoint is only
    # ever considered present after an explicit check sets this, never by
    # assumption. See ArtifactAvailability's docstring for why this is a
    # separate axis from lifecycle_state.
    availability: str = ArtifactAvailability.MISSING.value
    recovery_source: str | None = None   # e.g. "kaggle:guruprasathannadurai/orca-core-dpo-merge-export-v1" -- required when availability=REMOTE
    availability_note: str = ""

    def manifest_path(self) -> Path:
        validate_id(self.checkpoint_id, "checkpoint_id")
        return CHECKPOINT_DIR / f"{self.checkpoint_id}.json"

    def save(self) -> Path:
        path = self.manifest_path()
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)
        return path

    @classmethod
    def load(cls, checkpoint_id: str) -> "CheckpointRecord":
        validate_id(checkpoint_id, "checkpoint_id")
        path = CHECKPOINT_DIR / f"{checkpoint_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"No checkpoint record for '{checkpoint_id}'")
        with open(path) as f:
            return cls(**json.load(f))

    def verify_integrity(self, artifact_path: Path | None = None) -> bool:
        """
        Re-hashes the actual artifact (if reachable locally) and compares
        against the recorded checksum. Raises CorruptCheckpointError on
        mismatch rather than silently returning False, since a caller that
        forgets to check a bool return is exactly how a corrupt checkpoint
        gets silently loaded.

        Phase 21B.2.1 (§7-9): a merged checkpoint's `artifact_path` is a
        DIRECTORY (registered via hash_artifact_directory() in
        orca.registry.provenance.complete_training_run()), never a single
        file -- calling sha256_of_file() on a directory path here
        previously either raised IsADirectoryError or (worse, on some
        platforms) silently mismatched, meaning post-registration
        integrity verification used a DIFFERENT algorithm than
        registration for every directory-backed checkpoint this project
        actually produces. This method now branches explicitly (never
        guesses from the filename) on `path.is_dir()`: a directory is
        hashed with the exact same hash_artifact_directory() registration
        used; a single file (the only kind of checkpoint that existed
        before Phase 21B introduced directory-backed merged artifacts,
        preserved here for backward compatibility) is still hashed with
        sha256_of_file(), unchanged from before.
        """
        path = artifact_path or Path(self.artifact_path)
        if not path.exists():
            # Artifact not reachable from this machine (e.g. only exists on
            # Kaggle/remote storage) -- can't verify, but that's not the same
            # as corrupt. Caller must handle this explicitly.
            self.validation_state = "UNVALIDATED"
            return False
        if path.is_dir():
            actual = hash_artifact_directory(path)["manifest_digest"]
        else:
            actual = sha256_of_file(path)
        if actual != self.artifact_checksum:
            self.validation_state = "CORRUPT"
            raise CorruptCheckpointError(
                f"Checkpoint '{self.checkpoint_id}' failed integrity check: "
                f"recorded={self.artifact_checksum} actual={actual}"
            )
        self.validation_state = "VALID"
        self.availability = ArtifactAvailability.LOCAL.value
        return True

    def refresh_availability(self, artifact_path: Path | None = None) -> str:
        """
        Checks local file presence/integrity and sets availability to LOCAL
        or CORRUPT accordingly. Does NOT downgrade an existing REMOTE or
        ARCHIVED state to MISSING just because the file isn't locally
        present right now -- those states represent a deliberate, verified
        fact about a KNOWN remote location, which a missing local copy
        doesn't invalidate. Only call this after actually checking a
        specific local path; it never guesses.
        """
        path = artifact_path or Path(self.artifact_path)
        if not path.exists():
            if self.availability not in (ArtifactAvailability.REMOTE.value, ArtifactAvailability.ARCHIVED.value):
                self.availability = ArtifactAvailability.MISSING.value
            return self.availability
        try:
            self.verify_integrity(path)
        except CorruptCheckpointError:
            self.availability = ArtifactAvailability.CORRUPT.value
        return self.availability

    def is_loadable(self) -> bool:
        """
        The routing guard: a checkpoint whose weight artifact is not
        verified LOCAL must never be treated as loadable, regardless of
        its lifecycle_state. REMOTE means "recoverable with an explicit
        fetch step" -- still not loadable as-is.
        """
        return self.availability == ArtifactAvailability.LOCAL.value

    def is_routable(self) -> bool:
        return self.is_loadable()


def list_checkpoints(model_id: str | None = None) -> list[CheckpointRecord]:
    records = []
    for p in sorted(CHECKPOINT_DIR.glob("*.json")):
        with open(p) as f:
            rec = CheckpointRecord(**json.load(f))
        if model_id is None or rec.model_id == model_id:
            records.append(rec)
    return records


def latest_good_checkpoint(model_id: str, require_loadable: bool = False) -> CheckpointRecord | None:
    """
    Most recent checkpoint for a family that isn't marked CORRUPT. Pass
    require_loadable=True to additionally require the artifact be verified
    LOCAL -- the right choice for anything that intends to actually load
    the weights, as opposed to a lineage/history query.
    """
    candidates = [c for c in list_checkpoints(model_id) if c.validation_state != "CORRUPT"]
    if require_loadable:
        candidates = [c for c in candidates if c.is_loadable()]
    if not candidates:
        return None
    return max(candidates, key=lambda c: c.created_at)
