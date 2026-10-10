"""
Regression tests for ORNEUR — FINAL PRE-MERGE DEPENDENCY SECURITY
REMEDIATION (PYSEC-2026-2447 / CVE-2025-69872, PYSEC-2026-3447 /
CVE-2026-59890).

PYSEC-2026-2447 (diskcache <= 5.6.3, no upstream fix at time of writing):
unsafe pickle deserialization -- an attacker with write access to the
diskcache-backed directories under ORCA_HOME (orca/brain/memory.py's
SemanticMemory, orca/lens/queue.py's LensJobQueue) could plant a malicious
pickle that executes on the next read. With no patched diskcache release
available, the only real fix is denying that write access to anyone but
the owning user -- these tests assert every ORCA_HOME-relative store is
created (and retroactively corrected) to mode 0700.

PYSEC-2026-3447 (setuptools < 83.0.0): a MANIFEST.in exclude/prune rule
could be bypassed by an NFD-vs-NFC filename mismatch when building an
sdist on a Unicode-normalizing filesystem (macOS APFS/HFS+), packing a
file that should have been excluded. setuptools is not a direct
dependency here -- it is pulled in transitively by torch for
python_full_version >= '3.12' -- so the fix is a uv constraint-dependency
forcing the resolver to pick a patched version for that edge.
"""
from __future__ import annotations

import stat
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


# --- PYSEC-2026-2447: diskcache pickle RCE mitigation (directory ACL) ------

def test_mkdir_owner_only_creates_directory_restricted_to_owner(tmp_path):
    from orca.config import _mkdir_owner_only

    target = tmp_path / "fresh"
    _mkdir_owner_only(target)
    assert _mode(target) == 0o700


def test_mkdir_owner_only_retroactively_fixes_preexisting_loose_directory(tmp_path):
    """
    A directory created by an older, pre-remediation release of this code
    would already exist with looser (e.g. umask-default 0755) permissions.
    mkdir(exist_ok=True)'s `mode` argument is silently ignored for a
    directory that already exists, so without an explicit chmod every call
    after the first would leave a stale, attacker-writable-by-other-local-
    users directory in place forever. This must self-heal on every startup.
    """
    from orca.config import _mkdir_owner_only

    target = tmp_path / "preexisting"
    target.mkdir(mode=0o755)
    assert _mode(target) == 0o755

    _mkdir_owner_only(target)
    assert _mode(target) == 0o700


def test_mkdir_owner_only_creates_parents_restricted_when_requested(tmp_path):
    from orca.config import _mkdir_owner_only

    target = tmp_path / "a" / "b" / "c"
    _mkdir_owner_only(target, parents=True)
    assert target.is_dir()
    assert _mode(target) == 0o700


def test_orca_home_and_every_diskcache_backed_store_are_owner_only(tmp_path):
    """
    End-to-end check of the module's real startup path (not just the
    helper in isolation): a fresh process importing orca.config with a
    fresh ORNEUR_HOME must leave ORCA_HOME, MEMORY_DIR, CACHE_DIR and
    VAULT_DIR all at 0700. Run in a subprocess because orca.config has
    module-level side effects (directory creation) that only run once per
    interpreter -- re-importing in-process would not re-exercise them
    against a fresh directory.
    """
    home = tmp_path / "fresh_home"
    script = (
        "import stat, orca.config as c, json\n"
        "dirs = {'home': c.ORCA_HOME, 'memory': c.MEMORY_DIR, "
        "'cache': c.CACHE_DIR, 'vault': c.VAULT_DIR}\n"
        "print(json.dumps({k: stat.S_IMODE(v.stat().st_mode) for k, v in dirs.items()}))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        env={"ORNEUR_HOME": str(home), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr

    import json

    modes = json.loads(result.stdout)
    for name, mode in modes.items():
        assert mode == 0o700, f"{name} directory is {oct(mode)}, expected 0700"


def test_lens_queue_dir_is_owner_only(tmp_path):
    home = tmp_path / "fresh_home"
    script = (
        "import stat, orca.lens.queue as q, json\n"
        "print(json.dumps(stat.S_IMODE(q.QUEUE_DIR.stat().st_mode)))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        env={"ORNEUR_HOME": str(home), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr

    import json

    assert json.loads(result.stdout) == 0o700


# --- PYSEC-2026-3447: setuptools >= 83.0.0 via transitive uv constraint ---

def test_pyproject_pins_setuptools_above_the_unicode_normalization_advisory():
    """
    Must be an exact `==` pin, not a `>=` range: `uv pip install
    --require-hashes` (scripts/ci/run_rse_dependency_audit.sh, against
    requirements/rse.txt) picks up this project's [tool.uv] settings even
    for a plain `-r` install, and --require-hashes mode rejects any
    constraint that isn't pinned with `==` -- a `>=83.0.0` range form was
    tried first and broke that CI job; this guards against that recurring.
    """
    with open(REPO_ROOT / "pyproject.toml", "rb") as f:
        data = tomllib.load(f)

    constraints = data.get("tool", {}).get("uv", {}).get("constraint-dependencies", [])
    setuptools_constraints = [c for c in constraints if c.replace(" ", "").startswith("setuptools")]
    assert len(setuptools_constraints) == 1
    pin = setuptools_constraints[0].replace(" ", "")
    assert pin.startswith("setuptools=="), f"expected an exact '==' pin, got {pin!r}"

    version = tuple(int(x) for x in pin.split("==")[1].split(".")[:3])
    assert version >= (83, 0, 0), (
        f"pinned setuptools version {pin} is < 83.0.0, "
        "still vulnerable to PYSEC-2026-3447 / CVE-2026-59890"
    )


def test_lockfile_setuptools_entry_is_not_vulnerable_to_pysec_2026_3447():
    with open(REPO_ROOT / "uv.lock", "rb") as f:
        data = tomllib.load(f)

    setuptools_entries = [p for p in data["package"] if p["name"] == "setuptools"]
    assert len(setuptools_entries) == 1, "expected exactly one locked setuptools entry"

    version = tuple(int(x) for x in setuptools_entries[0]["version"].split(".")[:3])
    assert version >= (83, 0, 0), (
        f"locked setuptools version {setuptools_entries[0]['version']} is < 83.0.0, "
        "still vulnerable to PYSEC-2026-3447 / CVE-2026-59890"
    )


def test_setuptools_is_not_a_direct_runtime_dependency():
    """
    Documents the actual exposure for the record: setuptools is pulled in
    only as a transitive build-time dependency of torch on Python >= 3.12
    (the PYSEC-2026-3447 defect is in sdist-building's MANIFEST.in file
    matching, not anything this project invokes directly at runtime) -- it
    must stay out of [project.dependencies] so this stays a pure
    version-floor fix with no direct-dependency surface added.
    """
    with open(REPO_ROOT / "pyproject.toml", "rb") as f:
        data = tomllib.load(f)

    direct_deps = data["project"]["dependencies"]
    assert not any(d.lower().startswith("setuptools") for d in direct_deps)
