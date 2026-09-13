# ORNEUR Legacy Namespace Migration (Design Only — Not Executed)

This document separates two distinct future migrations that this closure
deliberately does NOT execute: the Python import namespace (`orca.*` →
`orneur.*`) and the filesystem user-data path (`~/.orca/` → `~/.orneur/`).
Both build on, and do not contradict, the prior planning-only
`docs/orneur/phase-0/BRAND_MIGRATION_PLAN.md`.

## A. Python namespace migration (`orca.*` → `orneur.*`)

### Current state (Stage 0)

- Public ORNEUR identity, legacy internal `orca.*` namespace — this is
  exactly where this closure leaves the codebase.
- `orneur.intelligence.ocl` already exists as a clean, ORNEUR-native
  package (Phase 17) — proof that new code can be written directly under
  `orneur.*` without waiting for the full migration.
- Both packages now ship in the built wheel (see
  `ORNEUR_PACKAGING_MIGRATION.md`).

### Staged plan

- **Stage 0 (current):** public ORNEUR identity; legacy internal
  `orca.*` namespace continues to host all pre-Phase-17 code.
- **Stage 1:** establish a full `orneur.*` facade/API — thin re-export
  modules under `orneur.*` that import from `orca.*`, so external callers
  can start writing `from orneur.registry import model_spec` etc. without
  any internal code moving yet. Verify with the exact same test suite,
  unmodified, run against the facade imports.
- **Stage 2:** move leaf modules gradually, one subpackage at a time
  (e.g. `orca.registry` → `orneur.registry`, updating the Stage-1 facade
  to re-export from the new location instead of the old one), each move
  as its own commit with full regression, per the discipline already used
  throughout Phase 15-17 of this project.
- **Stage 3:** compatibility shims — once a leaf module has moved,
  leave a deprecation-warning shim at its old `orca.*` location for one
  release cycle (mirroring `orneur_env()`'s existing `ORCA_*` →
  `ORNEUR_*` env-var pattern in `orca/config.py`).
- **Stage 4:** deprecation instrumentation — log/count actual usage of
  the old `orca.*` import paths in production (if telemetry exists) to
  learn whether any external consumer still depends on them before
  removal.
- **Stage 5:** removal only after migration evidence — delete the
  Stage-3 shims only once Stage-4 data (or an explicit compatibility
  window) shows they are no longer exercised.

### What must be covered before Stage 2 starts touching real modules

- **Imports** — 112 files per the Phase-0 census; a scripted rename with
  full test-suite re-run per Phase-0's own migration-ordering
  recommendation, not manual edits.
- **Pickled/serialized identifiers** — none currently found (OCL's
  `to_canonical_json`/`digest` never embed Python module paths); re-check
  at Stage 2 time for any new serialization introduced in the interim.
- **Module-qualified references in docs/comments** — e.g.
  `orca/config.py`'s own comments citing `docs/orneur/phase-0/...`; these
  reference doc paths, not Python paths, and are unaffected.
- **Entrypoints** — `[project.scripts]` in `pyproject.toml`; both
  `orneur` and `orca` currently point at `orca.cli:app`. At Stage 2/3,
  `orneur.cli:app` becomes the canonical target with `orca.cli:app` as a
  thin re-export.
- **Plugins/third-party consumers** — none identified; this project has
  no published plugin API today.
- **Migrations** — no database migration currently encodes a Python
  module path as data (verified: Postgres/SQLite schemas here store
  table/column data, not import paths).
- **Tests** — 264 files reference `orca.*` imports or fixtures (Phase-0
  census scope); Stage 2's scripted rename must update these in the same
  commit as the module move it accompanies, not separately.
- **Persisted config** — `.env`/`ORCA_*` environment variables (see §B.4
  below) are a separate axis from Python imports and already have their
  own compatibility resolver.
- **User data paths** — see §B below; deliberately kept independent of
  the Python-import migration since they carry real, irreplaceable user
  data and follow their own safety requirements.
- **CLI aliases** — `orca` as a console-script entry point is a
  user-facing compatibility promise independent of the internal Python
  import path; it can be retained past Stage 5 if real users depend on
  it, per §C below.

**This migration is NOT executed in this closure.** No import statement
was rewritten as part of this branding closure beyond what public-facing
text required (none were).

## B. Filesystem user-data path migration (`~/.orca/` → `~/.orneur/`)

### Current state

`orca/config.py`'s `orneur_env()` resolver already accepts `ORNEUR_HOME`
in preference to the deprecated `ORCA_HOME`, but the **literal default**
(when neither is set) is still `Path.home() / ".orca"`. A fresh install
today, with no environment override, still gets `~/.orca/`.

This directory can contain, for any existing real install:

- `auth.db` (user accounts, sessions)
- trained model artifacts and adapters
- training data
- memory/vault contents
- activation/license state

### Design for a safe migration (NOT implemented this closure)

**New install** (no `~/.orca/` and no `~/.orneur/` present): create and
use `~/.orneur/` directly. No migration needed.

**Existing install** (`~/.orca/` present, `~/.orneur/` absent): on first
run of a version that knows about the new path,

1. Detect `~/.orca/` exists and `~/.orneur/` does not.
2. Copy (not move) `~/.orca/` → `~/.orneur/`, preserving file permissions
   and timestamps (e.g. `shutil.copytree(..., copy_function=shutil.copy2)`).
3. Verify the copy succeeded (e.g. compare file counts/sizes, or hash
   critical files like `auth.db`) before treating the migration as done.
4. Only after verification, write a marker file (e.g.
   `~/.orneur/.migrated-from-orca`) so the copy is not repeated on every
   run.
5. Never delete `~/.orca/` automatically — leave it as a rollback path.
   A separate, explicit, user-initiated cleanup command can remove it
   later once the user has confirmed the new location works.

**Both directories present** (collision case — e.g. a user manually
created `~/.orneur/`, or a partial prior migration): do NOT overwrite
`~/.orneur/` silently. Prefer `~/.orneur/` (it's already the target,
someone/something put data there deliberately) and log a warning that
`~/.orca/` was NOT touched and may contain stale or additional data the
user should review manually.

**Required test coverage before implementation** (none of this exists
yet — this is the plan, not the code):

- Use a temporary `HOME` directory (e.g. `tmp_path` fixture +
  monkeypatching `Path.home()`) in every test — never touch the real
  developer/CI machine's actual home directory.
- Test: new install, no existing directory → creates `~/.orneur/` only.
- Test: existing `~/.orca/` with real-looking files → copied intact to
  `~/.orneur/`, `~/.orca/` untouched, marker file written.
- Test: both directories present → `~/.orneur/` used, `~/.orca/`
  untouched, warning logged.
- Test: copy interrupted/fails partway → no marker file written, next
  run retries cleanly (idempotent).
- Test: file permissions on migrated files match the source exactly.

### Why this is deferred, not implemented

Implementing this now, without the test coverage above, in a closure
whose primary mandate is identity/packaging (not data-migration
correctness), would risk exactly the kind of data-loss or silent-move
failure this project's own engineering discipline (see the entire Phase
15-17 TDD history) exists to prevent. `install.sh`'s `VENV_DIR` was
deliberately left at `${HOME}/.orca/venv` in this closure for the same
reason — changing it would split a fresh install's venv location from its
data location, which is worse, not better, until the real migration lands.

## C. CLI alias retention

The `orca` console-script entry point (`[project.scripts] orca =
"orca.cli:app"`) is retained as a permanent-until-evidence-says-otherwise
backward-compatibility alias. It is:

- Documented here as legacy, not taught in any new documentation (README,
  install.sh, and this closure's own docs all use `orneur` exclusively).
- Functionally identical to `orneur` (same Typer app object) — the CLI
  itself now identifies as ORNEUR (`orneur --help` and `orca --help` both
  print "Orneur — Intelligence, Without End." after this closure's fix),
  so the alias no longer causes the product to call itself "Orca."
- Not scheduled for removal in this document — removal requires usage
  evidence (Stage 4-equivalent for the CLI) this closure did not gather.

## D. Licensing token formats

Two live, stable token formats were identified and deliberately NOT
changed in this closure:

- **License keys** (`orca/license/keys.py:146`): `ORCA-{TIER}-...`. A
  future `ORNEUR-...` format is possible once `validate_key()` is
  extended to accept both prefixes (mirroring the `ORCA_*`/`ORNEUR_*`
  env-var dual-acceptance pattern already in `orca/config.py`), and once
  that dual-validation path has its own test coverage proving old,
  already-issued keys still validate. Neither the format change nor its
  tests were built this closure.
- **API keys** (`orca/auth/apikeys.py:79`): `athr_`-prefixed (an
  Atheris-derived prefix on customer-facing tokens). Same treatment
  required before any change: this is a live, issued token format, not
  cosmetic text.

No key was invalidated, reformatted, or reissued as part of this closure.
