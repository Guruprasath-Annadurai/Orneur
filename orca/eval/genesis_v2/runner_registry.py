"""Qualification runner identity: WHERE and by WHAT process private-split access (via orca.eval.genesis_v2.ledger) may eventually be attempted.
Registration binds identity/environment metadata only; it grants nothing by itself — orca.eval.genesis_v2.ledger.AccessLedger still requires the
runner to be pre-registered there too (a separate RegisteredProcess map, built from this record) AND V2 to be frozen before any private split
access is granted. No credential value is ever stored here — only credential SCOPE description."""
from __future__ import annotations

import hashlib
from pathlib import Path

SCHEMA_VERSION = "genesis-v2-qualification-runner-registry/1"
REGISTRY_PATH = "docs/orneur/authorization/QUALIFICATION_RUNNER_REGISTRY.json"
STATES = ("REGISTERED_NOT_AUTHORIZED", "AUTHORIZED", "REVOKED")
REQUIRED_FIELDS = ("runner_id", "runner_class", "os_runtime", "code_sha256", "allowed_purposes", "allowed_splits", "sandbox_image_digest",
                   "semantic_engine_digest", "storage_backend_verification_digest", "ledger_database_identity_digest", "network_policy",
                   "credential_scope", "state")


def empty_registry() -> dict:
    return {"schema_version": SCHEMA_VERSION, "records": []}


def validate_record(r) -> list:
    p = []
    if not isinstance(r, dict) or set(r) != set(REQUIRED_FIELDS):
        return [f"runner record schema mismatch: expected {sorted(REQUIRED_FIELDS)}, got {sorted(r) if isinstance(r, dict) else type(r)}"]
    if not isinstance(r["runner_id"], str) or not r["runner_id"]:
        p.append("runner_id required")
    if not isinstance(r["code_sha256"], str) or len(r["code_sha256"]) != 64:
        p.append("code_sha256 must be a sha256 hex digest")
    if not isinstance(r["allowed_purposes"], list) or not r["allowed_purposes"]:
        p.append("allowed_purposes must be a non-empty list")
    if not isinstance(r["allowed_splits"], list) or not r["allowed_splits"]:
        p.append("allowed_splits must be a non-empty list")
    if r["state"] not in STATES:
        p.append(f"state must be one of {STATES}")
    if r["network_policy"] != "none":
        p.append("a qualification runner's own network policy must be 'none' beyond the private-store read path it is explicitly granted")
    cred = r["credential_scope"]
    if not isinstance(cred, dict) or set(cred) != {"private_store_read", "public_repo_write", "training_credentials", "unrelated_cloud_credentials", "developer_tokens"}:
        p.append("credential_scope must enumerate exactly these booleans")
    elif any(cred[k] for k in ("public_repo_write", "training_credentials", "unrelated_cloud_credentials", "developer_tokens")):
        p.append("a qualification runner must not hold public-repo-write, training, unrelated-cloud or developer-token credentials")
    return p


def validate(doc) -> list:
    if not isinstance(doc, dict) or doc.get("schema_version") != SCHEMA_VERSION or not isinstance(doc.get("records"), list):
        return ["registry schema mismatch"]
    p, seen = [], set()
    for r in doc["records"]:
        p += validate_record(r)
        rid = r.get("runner_id") if isinstance(r, dict) else None
        if rid in seen:
            p.append(f"duplicate runner_id {rid}")
        seen.add(rid)
    return p


def code_sha256_of(paths: list) -> str:
    h = hashlib.sha256()
    for p in sorted(str(x) for x in paths):
        h.update(Path(p).read_bytes())
    return h.hexdigest()


def to_ledger_registered_processes(doc: dict):
    """Builds the {process_id: RegisteredProcess} map the ledger needs, from AUTHORIZED runner records only. REGISTERED_NOT_AUTHORIZED and
    REVOKED records grant nothing at the ledger."""
    from orca.eval.genesis_v2.ledger import RegisteredProcess
    return {r["runner_id"]: RegisteredProcess(r["runner_id"], r["code_sha256"], tuple(r["allowed_purposes"]), tuple(r["allowed_splits"]))
            for r in doc.get("records", []) if r["state"] == "AUTHORIZED"}
