"""
Invariant test: no first-party Python code may read an ORCA_* environment
variable directly via os.environ -- every real config variable must go
through orca.config.orneur_env() so the ORNEUR_* canonical precedence and
deprecation warning apply uniformly. Without this test, a new call site
added later could silently reintroduce an unmigrated ORCA_* read, and the
Phase 1.1 migration table (docs/orneur/phase-1/ENV_MIGRATION.md) would go
stale without anyone noticing.
"""
from __future__ import annotations

import re
from pathlib import Path

ORCA_ROOT = Path(__file__).resolve().parent.parent / "orca"

# Deliberately excluded from this invariant, with reasons -- see
# docs/orneur/phase-1/ENV_MIGRATION.md for the full disposition table:
_ALLOWED_DIRECT_READ_FILES = {
    # orneur_env() ITSELF must read os.environ directly -- it's the
    # resolver, there's nothing to delegate to.
    "orca/config.py",
    # This is a string TEMPLATE for a standalone script that runs on a bare
    # cloud GPU instance with no orca package installed -- it can't import
    # orneur_env, so it inlines the same ORNEUR-wins-over-ORCA precedence
    # directly as plain os.environ.get() calls within the generated text.
    "orca/train/cloud.py",
}

_DIRECT_ORCA_ENV_PATTERN = re.compile(
    r'os\.environ\.get\(\s*["\']ORCA_|os\.environ\[\s*["\']ORCA_|os\.getenv\(\s*["\']ORCA_'
)


def test_no_unmigrated_direct_orca_env_reads():
    offenders = []
    for path in ORCA_ROOT.rglob("*.py"):
        rel = str(path.relative_to(ORCA_ROOT.parent))
        if rel in _ALLOWED_DIRECT_READ_FILES:
            continue
        if "__pycache__" in rel:
            continue
        text = path.read_text(errors="replace")
        for m in _DIRECT_ORCA_ENV_PATTERN.finditer(text):
            line_no = text.count("\n", 0, m.start()) + 1
            offenders.append(f"{rel}:{line_no}")

    assert not offenders, (
        "Found direct os.environ ORCA_* reads that bypass orneur_env() "
        "(no ORNEUR_* precedence/deprecation warning applies to these): "
        + ", ".join(offenders)
    )


def test_orneur_env_itself_still_exists_and_is_the_single_resolver():
    """Sanity check that the exemption above isn't hiding a removed resolver."""
    from orca.config import orneur_env
    assert callable(orneur_env)
