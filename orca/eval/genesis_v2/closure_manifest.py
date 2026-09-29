"""Builds GENESIS_V2_PRE_CORPUS_CLOSURE_MANIFEST.json: a public-safe, hash-only bundle over every artifact this phase touched, so the
independent audit can verify nothing else silently changed. No secrets, no private paths, no private benchmark data — hashes and
booleans only."""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "genesis-v2-pre-corpus-closure-manifest/2"
RECORD_PATH = "docs/orneur/phase-21/GENESIS_V2_PRE_CORPUS_CLOSURE_MANIFEST.json"

# ARTIFACT_PATHS deliberately excludes RECORD_PATH itself: a file cannot correctly hash itself before it is finished being written.

ARTIFACT_PATHS = (
    "docs/orneur/authorization/AUTHORITY_REGISTRY.json",
    "docs/orneur/authorization/REVIEWER_REGISTRY.json",
    "docs/orneur/authorization/QUALIFICATION_RUNNER_REGISTRY.json",
    "docs/orneur/authorization/OWNER_AUTHORITY_KEY_GENERATION_PROCEDURE.md",
    "docs/orneur/authorization/REVIEWER_PATH_STATUS.md",
    "docs/orneur/authorization/CORPUS_GENERATION_AUTHORIZATION.json",
    "docs/orneur/authorization/CORPUS_GENERATION_AUTHORIZATION_SIGNING_RUNBOOK.md",
    "docs/orneur/authorization/CORPUS_GENERATOR_REGISTRY.json",
    "docs/orneur/phase-21/GENESIS_V2_BENCHMARK_PARTITION_ARCHITECTURE.md",
    "docs/orneur/phase-21/GENESIS_V2_HISTORICAL_CONTAMINATION_CONTROLS.md",
    "docs/orneur/phase-21/GENESIS_TRAINING_AND_ADAPTATION_CORPUS_INVENTORY.json",
    "docs/orneur/phase-21/GENESIS_V2_UNAVAILABLE_CORPUS_ACCEPTANCE_POLICY.json",
    "docs/orneur/phase-21/GENESIS_V2_SEMANTIC_ENGINE_RECORD.json",
    "docs/orneur/phase-21/GENESIS_V2_SANDBOX_QUALIFICATION_CANDIDATE_RECORD.json",
    "docs/orneur/phase-21/GENESIS_V2_QUALIFICATION_RUNNER_QUALIFICATION_RECORD.json",
    "docker/genesis_v2_sandbox/Dockerfile",
    "docs/orneur/phase-21/GENESIS_V2_VAULT_VERIFICATION.json",
    "docs/orneur/phase-21/GENESIS_V2_LEDGER_DEPLOYMENT_RECORD.json",
    "docs/orneur/phase-21/GENESIS_CAPABILITY_EVAL_V2_PREREGISTRATION_DRAFT.json",
    "docs/orneur/phase-21/GENESIS_V2_CORPUS_INVENTORY_ATTESTATION_PAYLOAD_TO_SIGN.signable",
    "orca/eval/genesis_v2/identity_registry.py", "orca/eval/genesis_v2/authority_registry.py", "orca/eval/genesis_v2/reviewer_registry.py",
    "orca/eval/genesis_v2/authorization.py", "orca/eval/genesis_v2/review.py", "orca/eval/genesis_v2/inventory.py",
    "orca/eval/genesis_v2/secret_manager.py", "orca/eval/genesis_v2/vault_admin.py", "orca/eval/genesis_v2/ledger_admin.py",
    "orca/eval/genesis_v2/sandbox.py", "orca/eval/genesis_v2/sandbox_qualification.py", "orca/eval/genesis_v2/runner_registry.py",
    "orca/eval/genesis_v2/runner_qualification.py", "orca/eval/genesis_v2/semantic.py", "orca/eval/genesis_v2/semantic_calibration.py",
    "orca/eval/genesis_v2/prereg.py", "orca/eval/genesis_v2/owner_preflight.py", "orca/eval/genesis_v2/privacy_scan.py",
    "orca/eval/genesis_v2/corpus_generation_authorization.py", "orca/eval/genesis_v2/isolation.py",
    "orca/eval/genesis_v2/operational_boundary.py", "orca/eval/genesis_v2/corpus_manifest.py", "orca/eval/genesis_v2/candidate_lineage.py",
    "orca/eval/genesis_v2/generator_registry.py",
)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _head_sha() -> str:
    r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=20)
    return r.stdout.strip() if r.returncode == 0 else "unknown"


def build(root: Path, preflight_result: dict) -> dict:
    """`built_from_parent_commit_sha` is `git rev-parse HEAD` AT BUILD TIME — i.e. the PARENT commit, honestly labeled as such, never
    claimed to be "the" exact/final SHA (that would be the circular claim: this file cannot know the SHA of the commit it is about to
    become part of). `manifest_commit_sha` is that later commit; it is null here and reported separately in the phase's final report
    after the commit is made — exactly the same two-step evidence pattern sandbox_qualification.py uses for its own exact-SHA problem.
    `artifact_hashes` are direct content hashes and need no commit SHA to be independently verifiable."""
    root = Path(root)
    artifact_hashes = {p: _sha(root / p) for p in ARTIFACT_PATHS if (root / p).is_file()}
    missing = [p for p in ARTIFACT_PATHS if not (root / p).is_file()]
    body = {
        "document": "GENESIS_V2_PRE_CORPUS_CLOSURE_MANIFEST", "schema_version": SCHEMA_VERSION,
        "built_from_parent_commit_sha": _head_sha(), "manifest_commit_sha": None,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "artifact_hashes": dict(sorted(artifact_hashes.items())), "missing_artifacts": missing,
        "owner_preflight_result": preflight_result.get("result"), "owner_preflight_checks": preflight_result.get("checks"),
        "status": "PRE_CORPUS_CLOSURE_EVIDENCE_ONLY",
        "note": ("built_from_parent_commit_sha is the commit that existed when this manifest was generated (most bundled artifacts, "
                 "including some in this same phase's commit, are hashed by content here, not claimed to live at that SHA). "
                 "manifest_commit_sha is intentionally null: the commit that actually introduces this file is only knowable after it "
                 "is made, and is reported in the phase's final report instead of self-referenced."),
        "authorizations": {"private_corpus_exists": False, "screen_exists": False, "qualification_holdout_exists": False,
                            "corpus_secret_exists": False, "operational_benchmark_aes_key_exists": False, "model_inference_authorized": False,
                            "gpu_authorized": False, "provider_inference_authorized": False, "training_authorized": False,
                            "spending_authorized": False, "foundation_selected": False, "v2_frozen": False, "corpus_generated": False},
    }
    body["manifest_sha256"] = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return body


def freshness_problems(root: Path, manifest: dict) -> list:
    """Detects a STALE manifest: artifact content hashes recorded in `manifest` no longer match the files on disk. Used by
    owner_preflight to fail closed if the closure manifest silently drifts out of sync with the artifacts it claims to bundle."""
    root = Path(root)
    problems = []
    for p, recorded in (manifest.get("artifact_hashes") or {}).items():
        f = root / p
        if not f.is_file():
            problems.append(f"{p}: artifact recorded in manifest no longer exists")
        elif _sha(f) != recorded:
            problems.append(f"{p}: artifact content hash no longer matches the manifest (stale evidence binding)")
    for p in ARTIFACT_PATHS:
        if p not in (manifest.get("artifact_hashes") or {}) and (root / p).is_file():
            problems.append(f"{p}: artifact exists but is missing from the manifest")
    return problems
