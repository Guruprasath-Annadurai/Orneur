"""
ORNEUR brand invariant (corporate identity closure). Fails if any active
PUBLIC surface (see docs/orneur/brand/ORNEUR_PUBLIC_SURFACE_MANIFEST.md)
reintroduces stale product-identity strings: the product calling itself
"Orca" (as opposed to the legitimate internal `orca.*` Python namespace),
"built by Atheris", or the unverified `atheris.ai`/unqualified
`orca.systems` domains.

This intentionally does NOT flag:
- `import orca`, `from orca...`, `orca.registry...` -- internal namespace
- historical docs under docs/orneur/phase-*/ -- the project's own audit trail
- test fixtures -- internal, not customer-facing
- the live `ORCA-` license-key prefix / `athr_` API-key prefix -- stable
  token formats, not branding (see ORNEUR_LEGACY_NAMESPACE_MIGRATION.md)
- internal JS identifiers (appendOrcaMsg, orca_token, etc.)

Every exclusion has a documented reason in the manifest doc; this test's
own ALLOWLIST mirrors that doc's "Allowlisted exceptions" table exactly.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Mirrors docs/orneur/brand/ORNEUR_PUBLIC_SURFACE_MANIFEST.md's
# "Active public surfaces" table exactly -- update both together.
PUBLIC_SURFACES = [
    "README.md",
    "pyproject.toml",
    "install.sh",
    "orca/character.py",
    "orca/tui.py",
    "orca/cli.py",
    "orca/serve/api.py",
    "orca/serve/web/index.html",
    "orca/serve/web/landing.html",
    "orca/serve/web/trust.html",
    "orca/upgrade.py",
]

# Patterns that indicate the PRODUCT is being called "Orca" (or Atheris),
# not a legitimate internal `orca.*` reference. Case-sensitive where it
# matters (e.g. "ORCA" as a standalone wordmark vs. "orca." as a module
# path prefix).
FORBIDDEN_PATTERNS = [
    # Whole-word "Orca" only -- \b prevents matching inside compound
    # internal identifiers like OrcaBrain/OrcaUltra/OrcaNano/OrcaCore
    # (legitimate internal Python class names, out of scope), while still
    # catching "Orca", "Orca's", "Orca-trained", "Orca TUI", etc.
    re.compile(r"(?<![\w.])\bOrca\b(?!\.\w)"),
    re.compile(r"\bORCA\b(?!_)"),  # standalone "ORCA" wordmark, not "ORCA_" env var prefix
    re.compile(r"built by Atheris", re.IGNORECASE),
    re.compile(r"Powered by Atheris", re.IGNORECASE),
    re.compile(r"atheris\.ai"),
    re.compile(r"(?<![\w/])orca\.systems"),
]

# Per-file allowlisted substrings -- mirrors the manifest doc's
# "Allowlisted exceptions" table. Each entry documents its own reason.
ALLOWLIST: dict[str, list[str]] = {
    "README.md": [
        "ORCA-PRO-XXXXX-XXXXX-XXXXX",  # real, current, stable license-key format
        "`orca/tools/search_grounding.py`",
        "`orca/docs/citation_check.py`",
        "(`orca/serve/routing.py`)",
    ],
    "orca/serve/web/index.html": [
        "appendOrcaMsg",
        "orcaEl",
        "orca-row",
        "orca_token",
    ],
    "orca/upgrade.py": [
        # Historical explanation of the orca-ai/"Orca Systems" investigation
        # inside the module docstring -- not live branding.
        '"orca-ai"', "Orca Systems", "github.com/orca-systems/orca",
    ],
    "install.sh": [
        # Header comment explaining why the old orca.systems URL is gone --
        # historical/explanatory, not a live instruction to use it.
        '"orca.systems" URL',
    ],
    "orca/cli.py": [
        "ORCA-PRO-...",  # real, current, stable license-key format shown in --help
    ],
}


def _strip_allowlisted(text: str, relpath: str) -> str:
    for allowed in ALLOWLIST.get(relpath, []):
        text = text.replace(allowed, "")
    return text


@pytest.mark.parametrize("relpath", PUBLIC_SURFACES)
def test_public_surface_has_no_stale_branding(relpath: str):
    path = REPO_ROOT / relpath
    assert path.exists(), f"public surface {relpath!r} listed in the manifest no longer exists"
    text = path.read_text(encoding="utf-8")
    text = _strip_allowlisted(text, relpath)

    violations = []
    for pattern in FORBIDDEN_PATTERNS:
        for match in pattern.finditer(text):
            start = max(0, match.start() - 40)
            end = min(len(text), match.end() + 40)
            violations.append(f"{pattern.pattern!r} matched {match.group()!r} near: ...{text[start:end]!r}...")

    assert not violations, f"{relpath} reintroduces stale branding:\n" + "\n".join(violations)


def test_public_surface_manifest_matches_this_test():
    """The manifest doc's active-surfaces table must list exactly the same
    files as PUBLIC_SURFACES -- keeps the doc and the test from silently
    diverging."""
    manifest = (REPO_ROOT / "docs/orneur/brand/ORNEUR_PUBLIC_SURFACE_MANIFEST.md").read_text(encoding="utf-8")
    for relpath in PUBLIC_SURFACES:
        assert relpath in manifest, f"{relpath} is in PUBLIC_SURFACES but not documented in the manifest"


def test_pyproject_name_is_not_the_squatted_third_party_package():
    """orca-ai on PyPI belongs to an unrelated third party ("Orca Systems")
    -- see ORNEUR_PACKAGING_MIGRATION.md. This project's distribution name
    must never silently revert to it."""
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "orca-ai"' not in pyproject


def test_upgrade_module_does_not_target_the_squatted_third_party_package():
    upgrade_src = (REPO_ROOT / "orca/upgrade.py").read_text(encoding="utf-8")
    assert '_PACKAGE   = "orca-ai"' not in upgrade_src
    assert '_PACKAGE   = "orneur"' in upgrade_src
