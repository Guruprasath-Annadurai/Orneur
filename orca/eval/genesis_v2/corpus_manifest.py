"""Cryptographic corpus manifest: the public-safe, digest-only record binding a generated corpus to the exact
corpus-generation authorization that permitted it. Implements the schema PROPOSED in
GENESIS_V2_BENCHMARK_PARTITION_ARCHITECTURE.md §5. No corpus exists yet — this module only validates the SHAPE and
the BINDING of a manifest a future generation step would produce; it never generates content and is never called
with real data in this phase."""
from __future__ import annotations

import hashlib
import json
import re

SCHEMA_VERSION = "genesis-v2-corpus-manifest/1"
REQUIRED_FIELDS = frozenset({"schema_version", "corpus_id", "eval_version", "generator_code_sha256", "generated_at_commit_sha",
                             "screen_digest", "qualification_holdout_digest", "per_category_item_counts",
                             "corpus_generation_authorization_id"})
_SHA64 = re.compile(r"^[0-9a-f]{64}$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_CORPUS_ID = re.compile(r"^gce2c-[0-9a-f]{32}$")


def validate_manifest(manifest) -> list:
    """Structural validity only — no filesystem or authorization access. Fail closed on any deviation."""
    p = []
    if not isinstance(manifest, dict):
        return ["manifest is not an object"]
    if set(manifest) != REQUIRED_FIELDS:
        return [f"manifest schema mismatch: expected {sorted(REQUIRED_FIELDS)}, got {sorted(manifest)}"]
    if manifest["schema_version"] != SCHEMA_VERSION:
        p.append("schema_version mismatch")
    if not (isinstance(manifest["corpus_id"], str) and _CORPUS_ID.match(manifest["corpus_id"])):
        p.append("corpus_id must look like gce2c-<32 hex>")
    if not isinstance(manifest["eval_version"], str) or not manifest["eval_version"]:
        p.append("eval_version required")
    for f in ("generator_code_sha256", "screen_digest", "qualification_holdout_digest"):
        if not (isinstance(manifest[f], str) and _SHA64.match(manifest[f])):
            p.append(f"{f} must be a sha256 hex digest")
    if not (isinstance(manifest["generated_at_commit_sha"], str) and _SHA40.match(manifest["generated_at_commit_sha"])):
        p.append("generated_at_commit_sha must be a 40-hex commit sha")
    counts = manifest["per_category_item_counts"]
    if not isinstance(counts, dict) or not counts or not all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in counts.values()):
        p.append("per_category_item_counts must be a non-empty dict of non-negative integers")
    if not (isinstance(manifest["corpus_generation_authorization_id"], str) and manifest["corpus_generation_authorization_id"].startswith("cgauth-")):
        p.append("corpus_generation_authorization_id must reference a real cgauth-<hex> authorization id")
    return p


def manifest_digest(manifest: dict) -> str:
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def binding_problems(manifest: dict, authorization_record: dict) -> list:
    """Cross-checks the manifest against the SPECIFIC authorization record that must have permitted it. Never trusts
    the manifest's own claims about the authorization — looks the authorization up and compares independently."""
    p = validate_manifest(manifest)
    if p:
        return p
    if not isinstance(authorization_record, dict):
        return ["authorization_record is not an object"]
    if authorization_record.get("status") != "AUTHORIZED":
        return ["referenced authorization is not AUTHORIZED"]
    if authorization_record.get("authorization_id") != manifest["corpus_generation_authorization_id"]:
        p.append("manifest.corpus_generation_authorization_id does not match the authorization record's own id")
    if authorization_record.get("authorized_commit_sha") != manifest["generated_at_commit_sha"]:
        p.append("manifest.generated_at_commit_sha does not match the authorization's authorized_commit_sha")
    scope = authorization_record.get("authorized_scope") or []
    if not {"SCREEN", "QUALIFICATION_HOLDOUT"} <= set(scope):
        p.append("authorization did not scope both SCREEN and QUALIFICATION_HOLDOUT, but the manifest claims both digests")
    return p
