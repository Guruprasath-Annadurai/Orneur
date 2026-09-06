"""
Registry isolation for orca.learning's own standalone/programmatic entry
points (Phase 12.1 spec §5-17). Default execution must NEVER write into
the developer's real `~/.orca/registry/` -- persistence is opt-in and
explicit, and safety must not depend on running under pytest (a bare
`python -m orca.learning.eval_harness` invocation, or a direct call to
`run_all()`/`prepare_training_experiment()` from a script, must be safe
by default with no environment variable or fixture required).

This is the SAME mechanism `tests/_learning_registry_isolation.py` uses
for pytest (monkeypatching the four registry directory module
attributes), reimplemented here without a pytest dependency so it works
everywhere. `tests/_learning_registry_isolation.py` was NOT changed to
import from here, deliberately -- pytest's `monkeypatch` fixture already
gives automatic restore-on-teardown even if a test raises, which this
module's plain try/finally also provides for non-pytest callers.
"""
from __future__ import annotations

import contextlib
import tempfile
from pathlib import Path

# Reused from orca.godmode.file_elevation's exact discipline: absolute,
# resolved paths (and descendants) an explicit persistence destination
# may never resolve into, regardless of what the caller names -- defense
# in depth on top of (never instead of) requiring an explicit,
# caller-supplied Path in the first place.
_HARD_DENYLIST = [
    Path("/etc").resolve(),
    Path("/root").resolve(),
    Path.home().joinpath(".ssh").resolve(),
    Path.home().joinpath(".aws").resolve(),
    Path.home().joinpath(".gnupg").resolve(),
    Path.home().joinpath(".orca", "auth.db").resolve(),
    Path.home().joinpath(".orca", "godmode").resolve(),
]


class UnsafeRegistryDestination(Exception):
    pass


def validate_persist_destination(path: Path) -> Path:
    """
    Resolves `path` (symlinks followed, exactly like
    `orca.godmode.file_elevation._resolve_within_root`) and rejects it if
    the resolved path falls inside the hard denylist. This function only
    ever receives a `Path` the CALLER passed explicitly (a human running a
    CLI flag, or a script's own literal argument) -- no function anywhere
    in `orca/learning/` derives a destination Path from `FailureEvent` or
    `CurriculumCandidate` field content; that is the actual security
    boundary (spec §21), not a runtime content filter on this string.
    """
    resolved = Path(path).expanduser().resolve()
    for denied in _HARD_DENYLIST:
        try:
            resolved.relative_to(denied)
            raise UnsafeRegistryDestination(f"Destination '{resolved}' falls inside a hard-denied path ('{denied}').")
        except ValueError:
            continue
    return resolved


@contextlib.contextmanager
def isolated_registry(destination: Path | None = None):
    """
    Points orca.registry.{dataset_manifest,training_run,checkpoint,
    evaluation_registry}'s directory module-attributes at `destination`
    (validated via `validate_persist_destination`) for the duration of the
    `with` block, or at a freshly created ephemeral `TemporaryDirectory`
    if `destination is None` (the default, safe path) -- then restores
    the original values on exit, even if the block raises (spec §11:
    "if standalone harness crashes halfway through: real registry remains
    unchanged").
    """
    import orca.registry.dataset_manifest as dataset_manifest_mod
    import orca.registry.training_run as training_run_mod
    import orca.registry.checkpoint as checkpoint_mod
    import orca.registry.evaluation_registry as evaluation_registry_mod

    targets = [
        (dataset_manifest_mod, "DATASET_MANIFEST_DIR", "datasets"),
        (training_run_mod, "TRAINING_RUN_DIR", "training_runs"),
        (checkpoint_mod, "CHECKPOINT_DIR", "checkpoints"),
        (evaluation_registry_mod, "EVALUATION_REGISTRY_DIR", "evaluations"),
    ]
    originals = [(mod, attr, getattr(mod, attr)) for mod, attr, _ in targets]
    tmp_ctx: tempfile.TemporaryDirectory | None = None

    try:
        if destination is None:
            tmp_ctx = tempfile.TemporaryDirectory(prefix="orneur-learning-isolated-")
            base = Path(tmp_ctx.name)
        else:
            base = validate_persist_destination(destination)
            base.mkdir(parents=True, exist_ok=True)

        for mod, attr, subdir in targets:
            new_dir = base / "registry" / subdir
            new_dir.mkdir(parents=True, exist_ok=True)
            setattr(mod, attr, new_dir)

        yield base
    finally:
        for mod, attr, original in originals:
            setattr(mod, attr, original)
        if tmp_ctx is not None:
            tmp_ctx.cleanup()
