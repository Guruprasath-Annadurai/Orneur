"""
State fingerprinting and staleness detection (Phase 11 spec §49-51).
Honest per-resource-kind support -- never pretends every provider
exposes a version/etag/revision.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from orca.simulation.contracts import StateFingerprint


def fingerprint_file(root: Path, relative_path: str) -> StateFingerprint:
    target = (root / relative_path)
    if not target.exists() or not target.is_file():
        return StateFingerprint(resource=relative_path, kind="UNAVAILABLE", value=None)
    content_hash = hashlib.sha256(target.read_bytes()).hexdigest()
    return StateFingerprint(resource=relative_path, kind="CONTENT_HASH", value=content_hash)


def fingerprint_unavailable(resource: str) -> StateFingerprint:
    """Used for connector/provider resources with no real
    version/etag/revision exposed in this codebase -- disclosed as
    UNAVAILABLE rather than fabricated."""
    return StateFingerprint(resource=resource, kind="UNAVAILABLE", value=None)


def is_stale(before: StateFingerprint, after: StateFingerprint) -> bool:
    """
    Fails OPEN only when fingerprinting itself is unavailable for this
    resource kind (spec §50: "do not pretend all providers support
    this") -- staleness cannot be detected at all in that case, so it is
    reported as such by the caller (via `SimulationResult.warnings`),
    never silently assumed fresh. When BOTH sides are real, comparable
    fingerprints, any difference is staleness.
    """
    if before.kind == "UNAVAILABLE" or after.kind == "UNAVAILABLE":
        return False
    return before.value != after.value


def fingerprinting_available(fp: StateFingerprint) -> bool:
    return fp.kind != "UNAVAILABLE"
