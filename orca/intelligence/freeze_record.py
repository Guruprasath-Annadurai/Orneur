"""Immutable freeze records for approved, versioned ORNEUR architecture artifacts.

A freeze record pins the audited commit, the exact-SHA CI run and the SHA-256 of every frozen file. It is created exclusively (never overwritten);
``verify_freeze_record`` recomputes the hashes, so any later edit to a frozen file fails a test until a NEW semantic version is issued.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

AUDITED_SHA = "9f42f814ffd16756a6960c255911e411e77e9059"
CI_RUN_ID = "36252659258"
FREEZE_DIR = "docs/orneur/intelligence/freeze"

ARTIFACTS = {
    "orneur.eternal-architecture": {
        "version": "1.1.0", "file": "FREEZE_orneur.eternal-architecture_1.1.0.json",
        "frozen_files": ["docs/orneur/intelligence/ORNEUR_ETERNAL_INTELLIGENCE_ARCHITECTURE.md", "docs/orneur/intelligence/ORNEUR_ETERNAL_INTELLIGENCE_ARCHITECTURE.json",
                         "docs/orneur/intelligence/ORNEUR_DISCOVERY_INTELLIGENCE.md", "docs/orneur/intelligence/ORNEUR_SELF_EVOLVING_EXPERT_MESH.md",
                         "docs/orneur/intelligence/ORNEUR_ARCHITECTURE_MIGRATION_PROTOCOL.md", "orca/intelligence/spec.py"],
        "note": "The frozen JSON's own freeze_status block was computed before the freeze (READY, frozen=false). That artifact is deliberately not edited; this record is the freeze."},
    "orneur.core-protocol": {
        "version": "1.1.0", "file": "FREEZE_orneur.core-protocol_1.1.0.json", "frozen_files": ["orca/intelligence/protocol.py"],
        "note": "Any semantic change to the protocol requires a new protocol version and a new freeze record."},
}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _canon(o) -> str:
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def build_freeze_record(root: Path, artifact: str) -> dict:
    a = ARTIFACTS[artifact]
    doc = {
        "record_type": "SEMANTIC_VERSION_FREEZE", "artifact": artifact, "version": a["version"], "status": "FROZEN",
        "audited_sha": AUDITED_SHA,
        "exact_sha_ci": {"run_id": CI_RUN_ID, "workflow": "Test Suite", "conclusion": "success",
                         "jobs": ["Deterministic Unit Tests", "Training Math Unit Tests (Torch)", "Production Container Build + Boot Smoke",
                                  "Dependency Vulnerability Scan (informational, base install only)"],
                         "verified_by": "gh run list --commit <audited_sha> at record creation: run 36252659258, conclusion success"},
        "audit": {"auditor": "independent ChatGPT audit", "result": "FREEZE APPROVED", "date": "2026-09-26",
                  "provenance": "reported by the owner in the phase instruction; this record cannot itself prove the audit"},
        "frozen_files": {p: _sha(root / p) for p in a["frozen_files"]},
        "future_changes_require_new_semantic_version": True, "note": a["note"],
    }
    doc["record_sha256"] = hashlib.sha256(_canon({k: v for k, v in doc.items() if k != "record_sha256"}).encode()).hexdigest()
    return doc


def write_freeze_records(root: Path) -> dict[str, str]:
    """Create each record exclusively. If it already exists it is verified, never rewritten."""
    out = {}
    d = root / FREEZE_DIR
    d.mkdir(parents=True, exist_ok=True)
    for art, a in ARTIFACTS.items():
        path = d / a["file"]
        rec = build_freeze_record(root, art)
        try:
            with open(path, "x", encoding="utf-8") as f:
                f.write(json.dumps(rec, indent=1, sort_keys=True) + "\n")
            out[art] = "CREATED"
        except FileExistsError:
            verify_freeze_record(root, path)
            out[art] = "EXISTS_VERIFIED"
    return out


def verify_freeze_record(root: Path, path: Path) -> dict:
    rec = json.loads(path.read_text(encoding="utf-8"))
    problems = []
    body = {k: v for k, v in rec.items() if k != "record_sha256"}
    if hashlib.sha256(_canon(body).encode()).hexdigest() != rec["record_sha256"]:
        problems.append("record_sha256 mismatch")
    for p, want in rec["frozen_files"].items():
        if not (root / p).exists() or _sha(root / p) != want:
            problems.append(f"frozen file changed: {p}")
    if problems:
        raise ValueError("; ".join(problems))
    return rec
