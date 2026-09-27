"""Builds GENESIS_V2_PRE_CORPUS_CLOSURE_MANIFEST.json: a public-safe, hash-only bundle over every artifact this phase touched, so the
independent audit can verify nothing else silently changed. No secrets, no private paths, no private benchmark data — hashes and
booleans only."""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "genesis-v2-pre-corpus-closure-manifest/1"
RECORD_PATH = "docs/orneur/phase-21/GENESIS_V2_PRE_CORPUS_CLOSURE_MANIFEST.json"

ARTIFACT_PATHS = (
    "docs/orneur/authorization/AUTHORITY_REGISTRY.json",
    "docs/orneur/authorization/REVIEWER_REGISTRY.json",
    "docs/orneur/authorization/QUALIFICATION_RUNNER_REGISTRY.json",
    "docs/orneur/authorization/OWNER_AUTHORITY_KEY_GENERATION_PROCEDURE.md",
    "docs/orneur/authorization/REVIEWER_PATH_STATUS.md",
    "docs/orneur/phase-21/GENESIS_TRAINING_AND_ADAPTATION_CORPUS_INVENTORY.json",
    "docs/orneur/phase-21/GENESIS_V2_UNAVAILABLE_CORPUS_ACCEPTANCE_POLICY.json",
    "docs/orneur/phase-21/GENESIS_V2_SEMANTIC_ENGINE_RECORD.json",
    "docs/orneur/phase-21/GENESIS_V2_SANDBOX_QUALIFICATION_CANDIDATE_RECORD.json",
    "docs/orneur/phase-21/GENESIS_V2_QUALIFICATION_RUNNER_QUALIFICATION_RECORD.json",
    "docker/genesis_v2_sandbox/Dockerfile",
    "docs/orneur/phase-21/GENESIS_V2_VAULT_VERIFICATION.json",
    "docs/orneur/phase-21/GENESIS_V2_LEDGER_DEPLOYMENT_RECORD.json",
    "docs/orneur/phase-21/GENESIS_CAPABILITY_EVAL_V2_PREREGISTRATION_DRAFT.json",
    "orca/eval/genesis_v2/identity_registry.py", "orca/eval/genesis_v2/authority_registry.py", "orca/eval/genesis_v2/reviewer_registry.py",
    "orca/eval/genesis_v2/authorization.py", "orca/eval/genesis_v2/review.py", "orca/eval/genesis_v2/inventory.py",
    "orca/eval/genesis_v2/secret_manager.py", "orca/eval/genesis_v2/vault_admin.py", "orca/eval/genesis_v2/ledger_admin.py",
    "orca/eval/genesis_v2/sandbox.py", "orca/eval/genesis_v2/sandbox_qualification.py", "orca/eval/genesis_v2/runner_registry.py",
    "orca/eval/genesis_v2/runner_qualification.py", "orca/eval/genesis_v2/semantic.py", "orca/eval/genesis_v2/semantic_calibration.py",
    "orca/eval/genesis_v2/prereg.py", "orca/eval/genesis_v2/owner_preflight.py", "orca/eval/genesis_v2/privacy_scan.py",
)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _current_sha() -> str:
    r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=20)
    return r.stdout.strip() if r.returncode == 0 else "unknown"


def build(root: Path, preflight_result: dict) -> dict:
    root = Path(root)
    artifact_hashes = {p: _sha(root / p) for p in ARTIFACT_PATHS if (root / p).is_file()}
    missing = [p for p in ARTIFACT_PATHS if not (root / p).is_file()]
    body = {
        "document": "GENESIS_V2_PRE_CORPUS_CLOSURE_MANIFEST", "schema_version": SCHEMA_VERSION,
        "exact_sha": _current_sha(), "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "artifact_hashes": dict(sorted(artifact_hashes.items())), "missing_artifacts": missing,
        "owner_preflight_result": preflight_result.get("result"), "owner_preflight_checks": preflight_result.get("checks"),
        "status": "PRE_CORPUS_CLOSURE_EVIDENCE_ONLY",
        "authorizations": {"private_corpus_exists": False, "screen_exists": False, "qualification_holdout_exists": False,
                            "corpus_secret_exists": False, "operational_benchmark_aes_key_exists": False, "model_inference_authorized": False,
                            "gpu_authorized": False, "provider_inference_authorized": False, "training_authorized": False,
                            "spending_authorized": False, "foundation_selected": False, "v2_frozen": False, "corpus_generated": False},
    }
    body["manifest_sha256"] = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return body
