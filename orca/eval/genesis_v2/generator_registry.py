"""Corpus-GENERATOR identity: deliberately SEPARATE from QUALIFICATION_RUNNER_REGISTRY.json (runner_registry.py).

A generator identity is authorized to WRITE PILOT_TRAIN/DEV/SCREEN/QUALIFICATION_HOLDOUT to the vault during the
pre-freeze generation step; it must never also be authorized to READ SCREEN/QUALIFICATION_HOLDOUT after freeze —
that is the qualification runner's distinct role, gated separately by orca.eval.genesis_v2.ledger.AccessLedger. A
single identity being registered as both a generator and a qualification runner defeats the separation this module
exists to enforce, so `validate()` flags that combination (an id present in both registries) as an error.

Registration binds identity/environment metadata only; it grants nothing by itself — `operational_boundary.py`
still requires state == "AUTHORIZED" here before any generation code path is permitted to proceed, and the
CORPUS_GENERATION_AUTHORIZATION owner signature is a separate, additional gate on top of this one."""
from __future__ import annotations

from pathlib import Path

SCHEMA_VERSION = "genesis-v2-corpus-generator-registry/1"
REGISTRY_PATH = "docs/orneur/authorization/CORPUS_GENERATOR_REGISTRY.json"
STATES = ("REGISTERED_NOT_AUTHORIZED", "AUTHORIZED", "REVOKED")
REQUIRED_FIELDS = ("generator_id", "os_runtime", "code_sha256", "allowed_artifact_classes", "network_policy",
                   "credential_scope", "state")


def empty_registry() -> dict:
    return {"schema_version": SCHEMA_VERSION, "records": []}


def validate_record(r) -> list:
    p = []
    if not isinstance(r, dict) or set(r) != set(REQUIRED_FIELDS):
        return [f"generator record schema mismatch: expected {sorted(REQUIRED_FIELDS)}, got {sorted(r) if isinstance(r, dict) else type(r)}"]
    if not isinstance(r["generator_id"], str) or not r["generator_id"]:
        p.append("generator_id required")
    if not isinstance(r["code_sha256"], str) or len(r["code_sha256"]) != 64:
        p.append("code_sha256 must be a sha256 hex digest")
    from orca.eval.genesis_v2.corpus_generation_authorization import ARTIFACT_CLASSES
    if not isinstance(r["allowed_artifact_classes"], list) or not r["allowed_artifact_classes"] or not set(r["allowed_artifact_classes"]) <= set(ARTIFACT_CLASSES):
        p.append(f"allowed_artifact_classes must be a non-empty subset of {ARTIFACT_CLASSES}")
    if r["state"] not in STATES:
        p.append(f"state must be one of {STATES}")
    if r["network_policy"] != "none":
        p.append("a generator's own network policy must be 'none' -- generation is deterministic/local, never fetches from a network")
    cred = r["credential_scope"]
    if not isinstance(cred, dict) or set(cred) != {"vault_write", "vault_read", "public_repo_write", "training_credentials",
                                                    "unrelated_cloud_credentials", "developer_tokens"}:
        p.append("credential_scope must enumerate exactly these booleans")
    elif any(cred[k] for k in ("public_repo_write", "training_credentials", "unrelated_cloud_credentials", "developer_tokens")):
        p.append("a generator must not hold public-repo-write, training, unrelated-cloud or developer-token credentials")
    elif cred.get("vault_read") is True:
        p.append("a generator must be WRITE-ONLY to the vault: vault_read=true would let it re-read a sealed private split it just wrote, "
                 "which is the qualification runner's distinct role, not the generator's")
    return p


def validate(doc, qualification_runner_doc: dict | None = None) -> list:
    if not isinstance(doc, dict) or doc.get("schema_version") != SCHEMA_VERSION or not isinstance(doc.get("records"), list):
        return ["registry schema mismatch"]
    p, seen = [], set()
    for r in doc["records"]:
        p += validate_record(r)
        gid = r.get("generator_id") if isinstance(r, dict) else None
        if gid in seen:
            p.append(f"duplicate generator_id {gid}")
        seen.add(gid)
    if qualification_runner_doc is not None:
        runner_ids = {r.get("runner_id") for r in (qualification_runner_doc.get("records") or []) if isinstance(r, dict)}
        overlap = seen & runner_ids
        if overlap:
            p.append(f"identity registered as BOTH a generator and a qualification runner (not separated): {sorted(overlap)}")
    return p


def load(path) -> tuple:
    """(doc_or_None, problems) — same fail-closed shape as identity_registry.load."""
    import json
    try:
        doc = json.loads(Path(path).read_text())
    except Exception as e:
        return None, [f"unreadable: {type(e).__name__}"]
    problems = validate(doc)
    return (doc, []) if not problems else (None, problems)
