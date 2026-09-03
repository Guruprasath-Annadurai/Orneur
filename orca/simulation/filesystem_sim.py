"""
Filesystem simulation (Phase 11 spec §23-25). The first real, deterministic
simulation domain: a temporary copy-on-write tree, real file operations
applied to the COPY only, then a real structured diff -- never a fake
"predicted" diff a model invents.

Path safety reuses `orca.godmode.file_elevation`'s exact
`_resolve_within_root`/`_is_denied` discipline (spec §25: simulation
cannot widen lease scope, and must respect the same denylist) rather
than a second, parallel path-safety implementation.
"""
from __future__ import annotations

import hashlib
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from orca.godmode.file_elevation import _is_denied, _resolve_within_root
from orca.simulation.contracts import (
    Assumption,
    BlastRadius,
    EffectConfidence,
    EffectType,
    PredictedEffect,
    Provenance,
    Reversibility,
    SimulationAction,
)

_SUPPORTED_OPERATIONS = {"create", "modify", "delete", "rename"}


@dataclass
class FileDiffEntry:
    path: str
    change: str              # "created" | "modified" | "deleted" | "renamed"
    size_before: int | None = None
    size_after: int | None = None
    content_hash_before: str | None = None
    content_hash_after: str | None = None
    new_path: str | None = None


@dataclass
class FilesystemSimulationOutcome:
    blocked: bool
    block_reason: str | None
    diff_entries: list[FileDiffEntry]
    predicted_effects: list[PredictedEffect]
    assumptions: list[Assumption]


def _content_hash(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def simulate_file_action(*, root: Path, action: SimulationAction) -> FilesystemSimulationOutcome:
    """
    `action.arguments` must contain `operation` (one of `create`/`modify`/
    `delete`/`rename`) and `path` (relative or absolute, resolved against
    `root` exactly like a real elevated write would be). `rename` also
    requires `new_path`. `create`/`modify` may carry `content`.

    A real temporary copy of `root` is made (`shutil.copytree`); the
    operation is applied to files inside that COPY ONLY; `root` itself is
    never touched. The copy is always removed before returning --
    simulation leaves no trace on disk.
    """
    root = root.resolve()
    operation = action.arguments.get("operation", "")
    raw_path = action.arguments.get("path", "")

    if operation not in _SUPPORTED_OPERATIONS:
        return FilesystemSimulationOutcome(blocked=True, block_reason=f"unsupported filesystem simulation operation: {operation!r}", diff_entries=[], predicted_effects=[], assumptions=[])

    with tempfile.TemporaryDirectory() as tmp:
        # .resolve() the temp root itself first -- on macOS, tempfile's
        # default temp dir lives under /var/folders/... which /tmp
        # symlinks to /private/var/folders/...; comparing an unresolved
        # sandbox_root against `_resolve_within_root()`'s fully-resolved
        # candidate would then spuriously report every path as
        # "escaping," since the two sides of the comparison would be the
        # same real directory spelled two different ways.
        sandbox_root = (Path(tmp).resolve() / "sandbox")
        if root.exists():
            shutil.copytree(root, sandbox_root)
        else:
            sandbox_root.mkdir(parents=True)

        target = _resolve_within_root(raw_path, sandbox_root)
        if target is None:
            return FilesystemSimulationOutcome(blocked=True, block_reason=f"path '{raw_path}' would escape the sandbox root or hit the denylist -- denied before any simulated write", diff_entries=[], predicted_effects=[], assumptions=[])

        rel_path = str(target.relative_to(sandbox_root))
        before_hash = _content_hash(target)
        before_size = target.stat().st_size if target.exists() and target.is_file() else None

        assumptions = [Assumption(
            description="target file's on-disk state at simulation time matches the state at real execution time",
            source="filesystem_snapshot", verification_state="UNVERIFIED",
            impact_if_false="predicted diff may not match the real diff -- see staleness/fingerprint checks before execution",
        )]

        if operation == "create":
            if target.exists():
                return FilesystemSimulationOutcome(blocked=True, block_reason=f"'{rel_path}' already exists -- 'create' would overwrite, use 'modify' instead", diff_entries=[], predicted_effects=[], assumptions=assumptions)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(action.arguments.get("content", ""))
            entry = FileDiffEntry(path=rel_path, change="created", size_after=target.stat().st_size, content_hash_after=_content_hash(target))
            effect = PredictedEffect(
                resource=rel_path, effect_type=EffectType.CREATE, before_reference=None,
                predicted_after_reference=entry.content_hash_after, reversibility=Reversibility.COMPENSATABLE,
                blast_radius=BlastRadius.SINGLE_OBJECT, confidence=EffectConfidence.HIGH,
                assumption_ids=[assumptions[0].assumption_id], provenance=Provenance.SIMULATION,
            )

        elif operation == "modify":
            if not target.exists():
                return FilesystemSimulationOutcome(blocked=True, block_reason=f"'{rel_path}' does not exist -- 'modify' requires an existing file, use 'create' instead", diff_entries=[], predicted_effects=[], assumptions=assumptions)
            target.write_text(action.arguments.get("content", ""))
            entry = FileDiffEntry(path=rel_path, change="modified", size_before=before_size, size_after=target.stat().st_size, content_hash_before=before_hash, content_hash_after=_content_hash(target))
            effect = PredictedEffect(
                resource=rel_path, effect_type=EffectType.UPDATE, before_reference=before_hash,
                predicted_after_reference=entry.content_hash_after, reversibility=Reversibility.COMPENSATABLE,
                blast_radius=BlastRadius.SINGLE_OBJECT, confidence=EffectConfidence.HIGH,
                assumption_ids=[assumptions[0].assumption_id], provenance=Provenance.SIMULATION,
            )

        elif operation == "delete":
            if not target.exists():
                return FilesystemSimulationOutcome(blocked=True, block_reason=f"'{rel_path}' does not exist -- nothing to delete", diff_entries=[], predicted_effects=[], assumptions=assumptions)
            target.unlink()
            entry = FileDiffEntry(path=rel_path, change="deleted", size_before=before_size, content_hash_before=before_hash)
            # A real filesystem delete with no backup mechanism is
            # IRREVERSIBLE, honestly -- never classified reversible
            # merely because an inverse "re-create" command exists
            # (spec §21's own explicit example: a sent email is not
            # reversible just because a correction can follow).
            effect = PredictedEffect(
                resource=rel_path, effect_type=EffectType.DELETE, before_reference=before_hash,
                predicted_after_reference=None, reversibility=Reversibility.IRREVERSIBLE,
                blast_radius=BlastRadius.SINGLE_OBJECT, confidence=EffectConfidence.HIGH,
                assumption_ids=[assumptions[0].assumption_id], provenance=Provenance.SIMULATION,
            )

        else:  # rename
            new_raw_path = action.arguments.get("new_path", "")
            new_target = _resolve_within_root(new_raw_path, sandbox_root)
            if new_target is None:
                return FilesystemSimulationOutcome(blocked=True, block_reason=f"new_path '{new_raw_path}' would escape the sandbox root or hit the denylist", diff_entries=[], predicted_effects=[], assumptions=assumptions)
            if not target.exists():
                return FilesystemSimulationOutcome(blocked=True, block_reason=f"'{rel_path}' does not exist -- nothing to rename", diff_entries=[], predicted_effects=[], assumptions=assumptions)
            new_rel_path = str(new_target.relative_to(sandbox_root))
            new_target.parent.mkdir(parents=True, exist_ok=True)
            target.rename(new_target)
            entry = FileDiffEntry(path=rel_path, change="renamed", new_path=new_rel_path, size_before=before_size, content_hash_before=before_hash)
            effect = PredictedEffect(
                resource=rel_path, effect_type=EffectType.MOVE, before_reference=before_hash,
                predicted_after_reference=new_rel_path, reversibility=Reversibility.COMPENSATABLE,
                blast_radius=BlastRadius.SINGLE_OBJECT, confidence=EffectConfidence.HIGH,
                assumption_ids=[assumptions[0].assumption_id], provenance=Provenance.SIMULATION,
            )

        return FilesystemSimulationOutcome(blocked=False, block_reason=None, diff_entries=[entry], predicted_effects=[effect], assumptions=assumptions)
