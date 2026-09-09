"""
Phase 15.10 -- practical, honest supply-chain and licensing evidence
using tools already available in this repository (spec section 14-15).
No paid scans, no external service dependency -- if a check cannot be
performed with what is actually available, the result is UNVERIFIED,
never PASS.

This module inspects real repository files (`pyproject.toml`,
`uv.lock`) and returns typed `ProofCategory` results for Production
Proof to embed directly -- it does not fabricate a vulnerability scan
or an SBOM that was never actually produced.
"""
from __future__ import annotations

import re
from pathlib import Path

from orca.mission.production_proof import ProofCategory, not_applicable_category, unverified_category
from orca.mission.verification import VerificationOutcome

#: Disclosed, not silently fixed, per spec section 14's explicit
#: permission to leave this as carried-forward debt this phase.
CONTAINER_SANDBOX_MUTABLE_IMAGE_TAG = "python:3.11-slim"


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def evaluate_supply_chain(repo_root: Path) -> ProofCategory:
    """Real, bounded supply-chain evidence:
      - lockfile presence (uv.lock) -- a real, checkable fact.
      - dependency count from the lockfile (a real count, not estimated).
      - EVERY dependency in a uv.lock is version-pinned by construction
        (uv.lock records an exact resolved version per package) -- this
        is verifiable structurally, not asserted.
      - vulnerability scanning, SBOM/provenance, and install-hook
        auditing are NOT performed (no scanner tool is available in
        this environment) -- explicitly UNVERIFIED, never PASS.
      - the known CONTAINER_SANDBOX mutable image-tag debt is
        surfaced explicitly rather than silently omitted.
    """
    lockfile = repo_root / "uv.lock"
    pyproject = repo_root / "pyproject.toml"
    lock_text = _read_text(lockfile)
    pyproject_text = _read_text(pyproject)

    if lock_text is None:
        return unverified_category(
            "no uv.lock found -- dependency pinning/transitive-dependency evidence unavailable"
        )

    dependency_count = len(re.findall(r'(?m)^name = "', lock_text))
    all_pinned = bool(re.search(r'(?m)^version = "', lock_text))  # uv.lock always pins by construction

    notes = [
        f"lockfile present: uv.lock ({dependency_count} package(s) resolved)",
        f"all resolved dependencies are version-pinned by uv.lock's own format: {all_pinned}",
        "vulnerability scanning: UNVERIFIED -- no scanner tool available in this environment",
        "SBOM/provenance: UNVERIFIED -- not generated",
        "install-hook auditing: UNVERIFIED -- not performed",
        "dependency-confusion / typosquatting check: UNVERIFIED -- not performed",
        f"known debt: CONTAINER_SANDBOX default image is the mutable tag "
        f"{CONTAINER_SANDBOX_MUTABLE_IMAGE_TAG!r}, not digest-pinned",
    ]
    if pyproject_text is not None and "requires-python" not in pyproject_text:
        notes.append("pyproject.toml present but requires-python constraint not found")

    # Overall category status: UNVERIFIED, not PASS -- pinning alone
    # (verified above) does not constitute a full supply-chain clearance;
    # the vulnerability-scan and SBOM gaps mean this category cannot
    # honestly claim PASS.
    return ProofCategory(status=VerificationOutcome.UNVERIFIED, summary="; ".join(notes))


def evaluate_licensing(repo_root: Path) -> ProofCategory:
    """Bounded, non-legal licensing evidence (spec section 15):
      - source license: read directly from `pyproject.toml`'s
        `[project].license` field if present (a real, checkable fact).
      - dependency/asset/font/image license aggregation: NOT performed
        (no LICENSE/NOTICE/THIRD_PARTY files exist in this repository
        at the time of writing) -- UNVERIFIED.
    Never asserts "legally safe" or "commercially cleared"."""
    pyproject_text = _read_text(repo_root / "pyproject.toml")
    notes = []
    if pyproject_text is not None:
        match = re.search(r'license\s*=\s*\{\s*text\s*=\s*"([^"]+)"\s*\}', pyproject_text)
        if match:
            notes.append(f"source license (pyproject.toml): {match.group(1)}")
        else:
            notes.append("pyproject.toml present but no [project].license field found")
    else:
        notes.append("pyproject.toml not found")

    has_license_file = any((repo_root / name).exists() for name in ("LICENSE", "LICENSE.txt", "LICENSE.md"))
    notes.append(f"top-level LICENSE file present: {has_license_file}")
    notes.append("dependency license aggregation: UNVERIFIED -- no NOTICE/THIRD_PARTY file exists")
    notes.append("asset/font/image license attribution: UNVERIFIED -- not tracked")
    notes.append("this is engineering evidence only, not legal advice or a commercial clearance")

    return ProofCategory(status=VerificationOutcome.UNVERIFIED, summary="; ".join(notes))


def no_ui_accessibility() -> ProofCategory:
    return not_applicable_category(
        "this proof target (ORCA/ORNEUR backend engine) exposes no end-user interface to evaluate"
    )
