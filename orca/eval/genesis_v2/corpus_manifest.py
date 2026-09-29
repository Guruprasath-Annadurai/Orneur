"""Cryptographic corpus manifest: the public-safe, digest-only record binding a generated corpus to the exact
corpus-generation authorization that permitted it. Implements the schema PROPOSED in
GENESIS_V2_BENCHMARK_PARTITION_ARCHITECTURE.md §5. No corpus exists yet — this module only validates the SHAPE and
the BINDING of a manifest a future generation step would produce; it never generates content and is never called
with real data in this phase."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

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


def verify_against_artifacts(manifest: dict, *, store, generator_code_root, expected_corpus_digest: str) -> list:
    """Verifies manifest fields against ACTUAL bytes, not just their syntactic hash shape:
      - `generator_code_sha256` is recomputed fresh from the real generator code on disk and compared — a
        syntactically valid but WRONG hash in the manifest is caught here, not accepted on the manifest's own word.
      - `screen_digest` / `qualification_holdout_digest` are checked by actually reading and decrypting both splits
        from the real encrypted vault (`store.read_split`, which itself fails closed on any tamper/wrong-key/
        truncation) and re-hashing the REAL plaintext bytes — never trusting the manifest's self-reported digest as
        proof an artifact was verified.
      - the combined corpus digest recomputed from those two REAL split digests must equal `expected_corpus_digest`
        (the value the generation process itself recorded, e.g. in the ledger or the authorization evidence) — this
        is the SEAL's own binding (`store.write_corpus`'s return value), independently reproduced here.

    `store` must be an already-opened `store.EncryptedFileStore` (or compatible) with the real decryption key; this
    function only ever reads through its public API, never handles key material itself. Requires the vault to
    exist — this is the after-generation verification step, not a pre-generation check."""
    from orca.eval.genesis_v2 import runner_registry as RN
    from orca.eval.genesis_v2 import spec as SPEC
    from orca.eval.genesis_v2 import store as ST
    p = validate_manifest(manifest)
    if p:
        return p
    real_code_files = sorted(Path(generator_code_root).glob("*.py"))
    real_code_sha256 = RN.code_sha256_of(real_code_files)
    if real_code_sha256 != manifest["generator_code_sha256"]:
        p.append("generator_code_sha256 does not match the ACTUAL current generator code on disk")
    try:
        screen_plain = store.read_split(manifest["corpus_id"], "SCREEN", expected_corpus_digest=expected_corpus_digest)
        holdout_plain = store.read_split(manifest["corpus_id"], "QUALIFICATION_HOLDOUT", expected_corpus_digest=expected_corpus_digest)
    except Exception as e:
        return p + [f"could not read/decrypt the real vault artifacts to verify against: {type(e).__name__}"]
    import hashlib as _hashlib
    real_screen_digest = _hashlib.sha256(screen_plain).hexdigest()
    real_holdout_digest = _hashlib.sha256(holdout_plain).hexdigest()
    if real_screen_digest != manifest["screen_digest"]:
        p.append("screen_digest does not match the ACTUAL decrypted SCREEN plaintext")
    if real_holdout_digest != manifest["qualification_holdout_digest"]:
        p.append("qualification_holdout_digest does not match the ACTUAL decrypted QUALIFICATION_HOLDOUT plaintext")
    real_corpus_digest = ST.corpus_digest_of({"SCREEN": real_screen_digest, "QUALIFICATION_HOLDOUT": real_holdout_digest})
    if real_corpus_digest != expected_corpus_digest:
        p.append("the real corpus digest (recomputed from actual decrypted content) does not match expected_corpus_digest")
    return p


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
