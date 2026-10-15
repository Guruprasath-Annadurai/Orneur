"""Checkpoint save / verify / load for the synthetic harness, built on orca.registry.checkpoint (hash_artifact_directory identity,
CheckpointRecord.verify_integrity, CorruptCheckpointError).

Properties (each has a failing-before test in tests/test_trainprep_checkpoint.py):
  * ATOMIC: files are written + fsynced into a temp directory which is renamed into place, THEN a sidecar manifest (the commit record) is
    written atomically. A crash at any point leaves either nothing or an orphan directory with no manifest, which is never loadable.
  * IMMUTABLE: an existing checkpoint is never overwritten.
  * VERIFIED-ONLY LOADING: there is no API that returns state without verification. load_state() accepts only a VerifiedCheckpoint, which
    verify_checkpoint() alone can mint (module-private seal), and re-hashes the exact bytes it parses (no verify-then-swap window).
  * Truncation, bit flips, added/removed files, symlinks, a missing or edited sidecar and a plan/step mismatch are all refused.
  * The digest can be cross-checked against the run ledger (an independent record), so editing BOTH a file and its sidecar is still caught.

Honest limit: this proves integrity against accidental corruption and casual tampering. An attacker who can rewrite the checkpoint, its sidecar
AND the ledger and its head anchor is outside what local files can prove (see the audit-log retention design).
"""
from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from orca.registry.checkpoint import (CheckpointRecord, CheckpointStructureInvalid, CorruptCheckpointError, hash_artifact_directory)
from orca.train.dryrun.canon import atomic_write_bytes, canonical_bytes, fsync_dir, hash_obj, sha256_hex
from orca.train.dryrun.toy import Plan, StateInvalid, TrainState, state_from_json_obj

CKPT_SCHEMA = "orneur-dryrun-checkpoint/1"
MANIFEST_SCHEMA = "orneur-dryrun-checkpoint-manifest/1"
MAX_STATE_BYTES = 8 * 1024 * 1024
_NAME = re.compile(r"^ckpt-\d{6}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")
_MANIFEST_KEYS = {"schema", "checkpoint_id", "run_id", "step", "plan_sha256", "artifact_checksum", "files", "manifest_sha256"}
_SEAL = object()


class CheckpointUnverified(CorruptCheckpointError):
    """The checkpoint could not be verified (missing/edited sidecar, wrong plan, wrong ledger digest, missing artifact, ...). It is refused."""


class SimulatedCrash(RuntimeError):
    """Test-only: raised by the `crash_at` fault hook of save_checkpoint to prove a crash mid-save cannot yield a loadable checkpoint."""


def checkpoint_name(step: int) -> str:
    return f"ckpt-{int(step):06d}"


@dataclass(frozen=True)
class CheckpointHandle:
    name: str
    directory: Path
    manifest_path: Path
    digest: str
    step: int


@dataclass(frozen=True)
class VerifiedCheckpoint:
    """Evidence that verify_checkpoint() succeeded for this exact directory. Cannot be constructed without the module seal."""
    name: str
    directory: Path
    digest: str
    step: int
    plan_sha256: str
    file_hashes: dict = field(default_factory=dict, compare=False)
    _seal: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._seal is not _SEAL:
            raise CheckpointUnverified("a VerifiedCheckpoint can only be produced by verify_checkpoint()")


def _manifest_path(root: Path, name: str) -> Path:
    return Path(root) / f"{name}.manifest.json"


def save_checkpoint(root, state: TrainState, plan: Plan, run_id: str, *, crash_at: str | None = None) -> CheckpointHandle:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    name = checkpoint_name(state.step)
    final, mpath = root / name, _manifest_path(root, name)
    if final.exists() or mpath.exists():
        raise FileExistsError(f"checkpoint {name} already exists and checkpoints are immutable")
    tmp = root / (".tmp-" + name + "-" + sha256_hex(os.urandom(16))[:8])
    tmp.mkdir()
    try:
        state_bytes = canonical_bytes(state.to_json_obj())
        meta_bytes = canonical_bytes({"schema": CKPT_SCHEMA, "step": state.step, "plan_sha256": plan.sha256, "state_sha256": state.sha256})
        atomic_write_bytes(tmp / "state.json", state_bytes)
        atomic_write_bytes(tmp / "meta.json", meta_bytes)
        fsync_dir(tmp)
        if crash_at == "files":
            raise SimulatedCrash("crash after writing files, before rename")
        os.rename(tmp, final)
        fsync_dir(root)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    if crash_at == "renamed":
        raise SimulatedCrash("crash after rename, before the manifest (commit record)")
    ident = hash_artifact_directory(final)
    body = {"schema": MANIFEST_SCHEMA, "checkpoint_id": name, "run_id": run_id, "step": state.step, "plan_sha256": plan.sha256,
            "artifact_checksum": ident["manifest_digest"], "files": ident["files"]}
    atomic_write_bytes(mpath, canonical_bytes({**body, "manifest_sha256": hash_obj(body)}))
    return CheckpointHandle(name, final, mpath, ident["manifest_digest"], state.step)


def _read_manifest(root: Path, name: str) -> dict:
    if not _NAME.match(name or ""):
        raise CheckpointUnverified("invalid checkpoint name")
    mpath = _manifest_path(root, name)
    try:
        raw = json.loads(mpath.read_bytes())
    except (OSError, ValueError) as e:
        raise CheckpointUnverified(f"{name}: sidecar manifest missing or unreadable (uncommitted checkpoint)") from e
    if not isinstance(raw, dict) or set(raw) != _MANIFEST_KEYS or raw["schema"] != MANIFEST_SCHEMA:
        raise CheckpointUnverified(f"{name}: sidecar manifest schema mismatch")
    body = {k: v for k, v in raw.items() if k != "manifest_sha256"}
    if raw["manifest_sha256"] != hash_obj(body):
        raise CheckpointUnverified(f"{name}: sidecar manifest was edited (self-hash mismatch)")
    if raw["checkpoint_id"] != name or not _SHA64.match(str(raw["artifact_checksum"])) or not _SHA64.match(str(raw["plan_sha256"])):
        raise CheckpointUnverified(f"{name}: sidecar manifest fields invalid")
    return raw


def verify_checkpoint(root, name: str, *, expected_plan_sha256: str, expected_digest: str | None = None,
                      expected_step: int | None = None, expected_run_id: str | None = None) -> VerifiedCheckpoint:
    """Raises CheckpointUnverified / CorruptCheckpointError for anything wrong; returns a VerifiedCheckpoint otherwise."""
    root = Path(root)
    man = _read_manifest(root, name)
    directory = root / name
    if directory.is_symlink() or not directory.is_dir():
        raise CheckpointUnverified(f"{name}: artifact directory missing or a symlink")
    if man["plan_sha256"] != expected_plan_sha256:
        raise CheckpointUnverified(f"{name}: checkpoint was produced by a different plan/config")
    if expected_step is not None and man["step"] != expected_step:
        raise CheckpointUnverified(f"{name}: step mismatch")
    if expected_run_id is not None and man["run_id"] != expected_run_id:
        raise CheckpointUnverified(f"{name}: checkpoint belongs to a different run (wrong run id)")
    if expected_digest is not None and man["artifact_checksum"] != expected_digest:
        raise CheckpointUnverified(f"{name}: digest differs from the independently recorded (ledger) digest")
    record = CheckpointRecord(
        checkpoint_id=name, model_id="synthetic-toy", run_id=man["run_id"], step_or_epoch=str(man["step"]), base_model="synthetic/toy-linear",
        dataset_manifest_ids=[], training_config_summary=man["plan_sha256"], optimizer_state_available=True, scheduler_state_available=True,
        tokenizer_identity="none", artifact_path=str(directory), artifact_checksum=man["artifact_checksum"])
    try:
        reachable = record.verify_integrity(directory)        # raises CorruptCheckpointError on any byte-level mismatch
    except CheckpointStructureInvalid as e:
        raise CheckpointUnverified(f"{name}: unsafe artifact structure: {e}") from e
    if not reachable:
        raise CheckpointUnverified(f"{name}: artifact not reachable")
    if [f["path"] for f in man["files"]] != ["meta.json", "state.json"]:
        raise CheckpointUnverified(f"{name}: unexpected file set")
    return VerifiedCheckpoint(name=name, directory=directory, digest=man["artifact_checksum"], step=man["step"],
                              plan_sha256=man["plan_sha256"], file_hashes={f["path"]: f["sha256"] for f in man["files"]}, _seal=_SEAL)


def load_state(vc, plan: Plan) -> TrainState:
    """The only way to read a checkpoint's state. Refuses anything that is not a VerifiedCheckpoint minted by verify_checkpoint()."""
    if not isinstance(vc, VerifiedCheckpoint) or vc._seal is not _SEAL:
        raise CheckpointUnverified("refusing to load an unverified checkpoint")
    if vc.plan_sha256 != plan.sha256:
        raise CheckpointUnverified("plan mismatch")
    path = vc.directory / "state.json"
    if path.is_symlink():
        raise CheckpointUnverified("state.json is a symlink")
    raw = path.read_bytes()
    if len(raw) > MAX_STATE_BYTES:
        raise CheckpointUnverified("state.json too large")
    if sha256_hex(raw) != vc.file_hashes.get("state.json"):
        raise CheckpointUnverified("state.json changed between verification and load")
    try:
        state = state_from_json_obj(json.loads(raw), plan)
    except (ValueError, StateInvalid) as e:
        raise CheckpointUnverified(f"state.json invalid: {e}") from e
    if state.step != vc.step:
        raise CheckpointUnverified("state step does not match the checkpoint step")
    return state


def list_checkpoint_names(root) -> list:
    """Names of directories that LOOK committed (have a sidecar). Oldest first. Says nothing about validity."""
    root = Path(root)
    if not root.is_dir():
        return []
    return sorted(p.name[: -len(".manifest.json")] for p in root.glob("ckpt-??????.manifest.json"))


def latest_verified(root, plan: Plan, *, expected_digests: dict | None = None, require_listed: bool = False,
                    expected_run_id: str | None = None) -> tuple:
    """Newest checkpoint that verifies, scanning back past corrupt ones (rollback to the last good). Returns (VerifiedCheckpoint | None,
    {name: reason} for every newer candidate that was rejected). `expected_digests` maps step -> digest from the run ledger."""
    rejected: dict = {}
    for name in reversed(list_checkpoint_names(root)):
        step = int(name.split("-")[1])
        if require_listed and step not in (expected_digests or {}):
            rejected[name] = "not recorded in the run ledger (written but never committed to the record)"
            continue
        try:
            return verify_checkpoint(root, name, expected_plan_sha256=plan.sha256, expected_step=step,
                                     expected_digest=(expected_digests or {}).get(step), expected_run_id=expected_run_id), rejected
        except CorruptCheckpointError as e:
            rejected[name] = str(e)
    return None, rejected


def _quarantine_path(root: Path, name: str) -> Path:
    qdir = Path(root) / "quarantine"
    qdir.mkdir(exist_ok=True)
    n = 0
    while (qdir / f"{name}.{n}").exists():
        n += 1
    return qdir / f"{name}.{n}"


def quarantine_checkpoint(root, name: str) -> Path:
    """Move a refused checkpoint (and its sidecar) aside so it can be inspected but never loaded, freeing the name for a clean re-save.
    Nothing is deleted: the evidence stays."""
    root = Path(root)
    if not _NAME.match(name):
        raise CheckpointUnverified("invalid checkpoint name")
    dest = _quarantine_path(root, name)
    dest.mkdir()
    for src in (root / name, _manifest_path(root, name)):
        if src.exists() or src.is_symlink():
            os.rename(src, dest / src.name)
    return dest


def quarantine_uncommitted(root) -> list:
    """Checkpoint directories with no committed sidecar (a crash between rename and commit). Moved aside; returns their names."""
    root = Path(root)
    moved = []
    if not root.is_dir():
        return moved
    for p in sorted(root.glob("ckpt-??????")):
        if _NAME.match(p.name) and not _manifest_path(root, p.name).exists():
            quarantine_checkpoint(root, p.name)
            moved.append(p.name)
    return moved
