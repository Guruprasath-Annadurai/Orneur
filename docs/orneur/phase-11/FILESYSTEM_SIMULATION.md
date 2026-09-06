# Phase 11 — Filesystem Simulation

`orca/simulation/filesystem_sim.py::simulate_file_action()` — the first
real, deterministic simulation domain.

## Mechanism

1. `shutil.copytree(root, sandbox_root, symlinks=True)` — a REAL
   temporary copy of the target root, symlinks preserved AS symlinks
   (not dereferenced).
2. `create`/`modify`/`delete`/`rename` applied to files INSIDE the copy
   ONLY. `root` itself is never opened for writing.
3. A real structured `FileDiffEntry` is produced: path, change type,
   size before/after, SHA-256 content hash before/after.
4. The temp directory is always removed (`tempfile.TemporaryDirectory()`
   context manager) — simulation leaves no trace on disk.

## Path safety

Reuses `orca.godmode.file_elevation._resolve_within_root()`/`_is_denied()`
exactly — the same realpath-resolution discipline and hard denylist
(`/etc`, `/root`, `~/.ssh`, `~/.aws`, `~/.gnupg`, `auth.db`, Godmode's own
lease store) already proven in Phase 10. A path that would escape the
sandbox root, or that hits the denylist, is BLOCKED before any simulated
write — verified directly with a traversal path (`../../etc/evil.txt`).

## Real bug found and fixed: symlink dereferencing during copy

`shutil.copytree()`'s default behavior FOLLOWS symlinks and copies their
TARGET's content as a plain file — so a symlink pointing outside the
sandbox root was silently "defused" by the copy step itself, before
`_resolve_within_root()` ever got a chance to see it. This meant
simulation diverged from what a REAL elevated write through the same
path would do (real execution resolves the symlink against the REAL
root and correctly blocks the escape). Fixed with
`copytree(..., symlinks=True)`, so the simulated copy preserves the live
symlink and the exact same containment check blocks it identically.
Verified: `tests/test_simulation_security.py::test_sandbox_cannot_escape_via_symlink`
confirms the real target file's content is untouched.

## Reversibility classification

- `create`: `COMPENSATABLE` (an inverse delete exists).
- `modify`: `COMPENSATABLE` (the before-content hash is captured).
- `delete`: `IRREVERSIBLE` — honestly, since no backup mechanism exists.
  Never classified reversible merely because a "re-create" command could
  theoretically follow (spec §21's own example: a sent email is not
  reversible just because a correction can be sent).
- `rename`: `COMPENSATABLE` (an inverse rename exists).

## Directory-scoped Godmode leases (spec §25)

A `FILE`-domain Godmode lease's `resource_scope` IS the sandbox/real
root `simulate_file_action()` operates against — the simulator cannot
widen it, because `_resolve_within_root()` is applied against that exact
root, not a broader one. Verified end-to-end in
`tests/test_simulation_e2e.py::test_godmode_end_to_end_with_simulation`.
