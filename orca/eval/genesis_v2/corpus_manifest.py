"""Cryptographic corpus manifest: the public-safe, digest-only record binding a generated corpus to the exact
corpus-generation authorization that permitted it. Implements the schema PROPOSED in
GENESIS_V2_BENCHMARK_PARTITION_ARCHITECTURE.md §5. No corpus exists yet — this module only validates the SHAPE and
the BINDING of a manifest a future generation step would produce; it never generates content and is never called
with real data in this phase.

## Schema /2: the manifest is a SIGNED, post-generation authenticated record — not the pre-generation authorization

`corpus_generation_authorization.py`'s CGA record is signed BEFORE generation and binds the reviewed code and
evidence state that PERMITS generation to happen — it cannot and does not contain the digest of content that does
not exist yet at signing time. The X25519 vault keypair provides CONFIDENTIALITY (only the private-key holder can
decrypt) but NOT sender authentication — anyone who obtains the vault's public key can encrypt arbitrary content
into a syntactically valid, well-formed sealed corpus. The manifest is therefore the SEPARATE, POST-generation
authenticated record that binds corpus identity + real split digests + the combined corpus digest to the SPECIFIC
authorization that permitted its creation, via a real Ed25519 signature from a registered OWNER authority key
(the SAME authority_registry.py / role vocabulary already used for CGA) — `manifest_signing_bytes()` /
`verify_manifest_signature()` below, mirroring `corpus_generation_authorization.py`'s own
`canonical_signing_bytes()`/`verify_signature()` pattern exactly. A manifest without a valid signature from a
registered OWNER key is never a trusted source of `expected_corpus_digest` for anything downstream — see
`operational_boundary.verify_manifest_digest_only_same_process()`, which now derives that digest ONLY from a
manifest that has independently passed BOTH this signature check AND `binding_problems()`."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

SCHEMA_VERSION = "genesis-v2-corpus-manifest/2"
REQUIRED_FIELDS = frozenset({"schema_version", "corpus_id", "eval_version", "generator_code_sha256", "generated_at_commit_sha",
                             "screen_digest", "qualification_holdout_digest", "per_category_item_counts",
                             "corpus_generation_authorization_id", "signing_authority", "signature"})
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
    sa = manifest.get("signing_authority")
    if not isinstance(sa, dict) or set(sa) != {"identity", "role", "key_id"} or not all(isinstance(sa[k], str) and sa[k] for k in sa):
        p.append("signing_authority must be an object with non-empty identity/role/key_id strings")
    if not isinstance(manifest.get("signature"), str) or not manifest["signature"]:
        p.append("signature must be a non-empty string")
    return p


def manifest_signing_bytes(manifest: dict) -> bytes:
    """Canonical bytes the manifest's signature covers -- every field EXCEPT `signature` itself, mirroring
    corpus_generation_authorization.canonical_signing_bytes() exactly (the same self-referential-exclusion
    pattern: a record cannot sign over its own signature field)."""
    body = {k: v for k, v in manifest.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


def verify_manifest_signature(manifest: dict, keys: list) -> str | None:
    """Returns None if the manifest's signature is genuinely valid AND from a registered, active OWNER authority
    key; else a reason string. Never raises. Mirrors corpus_generation_authorization.verify_signature() exactly —
    same role restriction (OWNER only), same registered-key lookup, same Ed25519 verification, same fail-closed
    exception handling."""
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except Exception:
        return "SIGNATURE_VERIFIER_UNAVAILABLE"
    sa = manifest.get("signing_authority") or {}
    if not isinstance(sa, dict):
        return "MALFORMED_SIGNING_AUTHORITY"
    key = next((k for k in keys if isinstance(k, dict) and k.get("key_id") == sa.get("key_id")), None)
    if key is None:
        return "AUTHORITY_KEY_NOT_REGISTERED"
    if key.get("role") != "OWNER" or key.get("role") != sa.get("role") or key.get("identity") != sa.get("identity"):
        return "AUTHORITY_NOT_OWNER_OR_IDENTITY_MISMATCH"
    try:
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(key["public_key_hex"]))
        pub.verify(bytes.fromhex(str(manifest.get("signature") or "")), manifest_signing_bytes(manifest))
    except InvalidSignature:
        return "INVALID_SIGNATURE"
    except Exception as e:
        return f"SIGNATURE_CHECK_ERROR:{type(e).__name__}"
    return None


def manifest_digest(manifest: dict) -> str:
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def verify_against_artifacts(manifest: dict, *, screen_plain: bytes, holdout_plain: bytes, generator_code_root,
                              expected_corpus_digest: str) -> list:
    """Verifies manifest fields against ACTUAL bytes, not just their syntactic hash shape:
      - `generator_code_sha256` is recomputed fresh from the real generator code on disk and compared — a
        syntactically valid but WRONG hash in the manifest is caught here, not accepted on the manifest's own word.
      - `screen_digest` / `qualification_holdout_digest` are checked against the REAL decrypted plaintext bytes —
        never trusting the manifest's self-reported digest as proof an artifact was verified.
      - the combined corpus digest recomputed from those two REAL split digests must equal `expected_corpus_digest`.

    IMPORTANT — this function does NOT read the vault itself and never holds a store or key. `screen_plain` /
    `holdout_plain` must already be authorized, decrypted bytes the CALLER obtained through
    `operational_boundary.require_private_split_access()` (the real ledger-gated path — qualification-runner
    identity, V2-frozen state, purpose, and an actual ledger grant, all enforced there). Handing this function a raw
    `store` to read from directly would let verification silently bypass the ledger entirely, exactly the class of
    bug an earlier version of this function had (a generator or any other caller with a store handle could
    "verify" — and thereby read — a holdout without ever being an authorized qualification runner). This function
    is deliberately read-nothing: it only ever hashes bytes it is handed."""
    from orca.eval.genesis_v2 import runner_registry as RN
    from orca.eval.genesis_v2 import store as ST
    p = validate_manifest(manifest)
    if p:
        return p
    if not isinstance(screen_plain, (bytes, bytearray)) or not isinstance(holdout_plain, (bytes, bytearray)):
        return p + ["screen_plain/holdout_plain must be the actual authorized plaintext bytes, not read here"]
    real_code_files = sorted(Path(generator_code_root).glob("*.py"))
    real_code_sha256 = RN.code_sha256_of(real_code_files)
    if real_code_sha256 != manifest["generator_code_sha256"]:
        p.append("generator_code_sha256 does not match the ACTUAL current generator code on disk")
    real_screen_digest = hashlib.sha256(bytes(screen_plain)).hexdigest()
    real_holdout_digest = hashlib.sha256(bytes(holdout_plain)).hexdigest()
    if real_screen_digest != manifest["screen_digest"]:
        p.append("screen_digest does not match the ACTUAL decrypted SCREEN plaintext")
    if real_holdout_digest != manifest["qualification_holdout_digest"]:
        p.append("qualification_holdout_digest does not match the ACTUAL decrypted QUALIFICATION_HOLDOUT plaintext")
    real_corpus_digest = ST.corpus_digest_of({"SCREEN": real_screen_digest, "QUALIFICATION_HOLDOUT": real_holdout_digest})
    if real_corpus_digest != expected_corpus_digest:
        p.append("the real corpus digest (recomputed from actual decrypted content) does not match expected_corpus_digest")
    return p


def binding_problems(manifest: dict, authorization_record: dict, *, commit_is_descendant: bool) -> list:
    """Cross-checks the manifest against the SPECIFIC authorization schema /2 record that must have permitted it.
    Never trusts the manifest's own claims about the authorization — looks the authorization up and compares
    independently, using the SAME ancestry + code-tree-hash binding as corpus_generation_authorization.py itself
    (never literal commit-SHA equality — see that module's docstring for why that would be circular/always-false).

    `commit_is_descendant` — whether `manifest["generated_at_commit_sha"]` is `authorization_record["reviewed_commit_sha"]`
    itself or a genuine git descendant of it — MUST be computed by the caller (e.g. via
    `operational_boundary._is_ancestor` / `git merge-base --is-ancestor`); this module does no git I/O itself so it
    stays trivially testable with synthetic fixtures."""
    p = validate_manifest(manifest)
    if p:
        return p
    if not isinstance(authorization_record, dict):
        return ["authorization_record is not an object"]
    if authorization_record.get("status") != "AUTHORIZED":
        return ["referenced authorization is not AUTHORIZED"]
    if authorization_record.get("authorization_id") != manifest["corpus_generation_authorization_id"]:
        p.append("manifest.corpus_generation_authorization_id does not match the authorization record's own id")
    reviewed_sha = authorization_record.get("reviewed_commit_sha")
    if not (isinstance(reviewed_sha, str) and reviewed_sha):
        p.append("authorization record has no reviewed_commit_sha to bind against")
    elif commit_is_descendant is not True:
        p.append("manifest.generated_at_commit_sha is not the authorization's reviewed_commit_sha or a verified descendant of it")
    if authorization_record.get("authorized_code_tree_sha256") != manifest["generator_code_sha256"]:
        p.append("manifest.generator_code_sha256 does not match the authorization's authorized_code_tree_sha256")
    scope = authorization_record.get("authorized_scope") or []
    if not {"SCREEN", "QUALIFICATION_HOLDOUT"} <= set(scope):
        p.append("authorization did not scope both SCREEN and QUALIFICATION_HOLDOUT, but the manifest claims both digests")
    return p
