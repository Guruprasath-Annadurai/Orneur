"""Generation receipt: durable, authenticated evidence of WHEN a specific corpus was actually generated, binding
that event to the specific CORPUS_GENERATION_AUTHORIZATION that permitted it and the specific signed manifest that
describes its content. Implements items 1-2 of the generation-provenance-closure phase.

## Why a SEPARATE record from the CGA and the manifest

`corpus_generation_authorization.verify_referenced()` (receiving-boundary-integration phase) deliberately allows a
historical, expired CGA to still be authenticated -- auditing something already generated must not fail merely
because its authorization's short validity window has since elapsed. That is the correct behavior for AUTHENTICATING
an authorization record's own signature. It does NOT, by itself, prove the corpus was actually generated WHILE that
authorization was genuinely valid -- a CGA's authenticity says nothing about WHEN generation happened. Without a
separate, durable, signed record of the generation TIME, a corpus produced (or claimed to be produced) entirely
outside its authorization's validity window could still pass every other check: the CGA still verifies as authentic
(by design, regardless of elapsed time), and the manifest's own Ed25519 signature says nothing about timing either.

This module closes that gap with the smallest additional signed record: a GENERATION RECEIPT, created once, at
generation time, and durably retained alongside the manifest. It binds corpus_generation_authorization_id, corpus_id,
eval_version, the combined corpus_digest, generator_code_tree_sha256, generating_commit_sha, generator_identity,
generated_at (the actual generation timestamp), and an attesting_authority + signature: a real Ed25519 signature
from a registered, ACTIVE, OWNER authority key SCOPED for corpus generation (see
`corpus_generation_authorization.load_keys_for_corpus_generation()`) -- the SAME kind of signature the CGA/manifest
already use, applied to a THIRD, independent claim: not "generation is authorized" (the CGA) and not "this is the
generated content" (the manifest), but "generation genuinely happened at this specific time."

The receiving path (`operational_boundary.verify_manifest_digest_only_same_process()`) verifies this receipt
cryptographically and requires `authorization.issued_at <= receipt.generated_at <= authorization.expires_at` --
using the AUTHORIZATION'S OWN window, never the CURRENT verification-time clock (using "now" here would make the
exact same "can a stale-but-real generation still be trusted" mistake `verify_referenced()` deliberately avoids for
the CGA's own signature check, just moved into an even harder-to-notice place, since verification can legitimately
happen long after generation). A corpus with an authentic-but-expired historical CGA and NO valid in-window
generation receipt is never accepted as proven authorized-generation output -- receipt absence, an unsigned/forged
receipt, a mismatched binding, or an out-of-window timestamp are all hard failures, never soft warnings."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

SCHEMA_VERSION = "genesis-v2-generation-receipt/1"
REQUIRED_FIELDS = frozenset({"schema_version", "corpus_generation_authorization_id", "corpus_id", "eval_version",
                             "corpus_digest", "generator_code_tree_sha256", "generating_commit_sha",
                             "generator_identity", "generated_at", "attesting_authority", "signature"})
_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")
_CORPUS_ID = re.compile(r"^gce2c-[0-9a-f]{32}$")
_ID = re.compile(r"^cgauth-[0-9a-f]{16,64}$")


def default_receipt() -> dict:
    return {"schema_version": SCHEMA_VERSION, "corpus_generation_authorization_id": None, "corpus_id": None,
            "eval_version": None, "corpus_digest": None, "generator_code_tree_sha256": None, "generating_commit_sha": None,
            "generator_identity": None, "generated_at": None, "attesting_authority": {"identity": None, "role": None, "key_id": None},
            "signature": None}


def _parse(s) -> datetime | None:
    if not isinstance(s, str) or not _TS.match(s):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def validate_receipt(receipt) -> list:
    """Structural validity only -- no filesystem, authorization, or manifest access. Fail closed on any deviation."""
    p: list = []
    if not isinstance(receipt, dict):
        return ["RECEIPT_NOT_AN_OBJECT"]
    if set(receipt) != REQUIRED_FIELDS:
        return [f"RECEIPT_SCHEMA_MISMATCH: expected {sorted(REQUIRED_FIELDS)}, got {sorted(receipt)}"]
    if receipt["schema_version"] != SCHEMA_VERSION:
        p.append("schema_version mismatch")
    if not (isinstance(receipt["corpus_generation_authorization_id"], str) and _ID.match(receipt["corpus_generation_authorization_id"])):
        p.append("corpus_generation_authorization_id must reference a real cgauth-<hex> authorization id")
    if not (isinstance(receipt["corpus_id"], str) and _CORPUS_ID.match(receipt["corpus_id"])):
        p.append("corpus_id must look like gce2c-<32 hex>")
    if not isinstance(receipt["eval_version"], str) or not receipt["eval_version"]:
        p.append("eval_version required")
    if not (isinstance(receipt["corpus_digest"], str) and _SHA64.match(receipt["corpus_digest"])):
        p.append("corpus_digest must be a sha256 hex digest")
    if not (isinstance(receipt["generator_code_tree_sha256"], str) and _SHA64.match(receipt["generator_code_tree_sha256"])):
        p.append("generator_code_tree_sha256 must be a sha256 hex digest")
    if not (isinstance(receipt["generating_commit_sha"], str) and _SHA40.match(receipt["generating_commit_sha"])):
        p.append("generating_commit_sha must be a 40-hex commit sha")
    if not isinstance(receipt["generator_identity"], str) or not receipt["generator_identity"]:
        p.append("generator_identity required")
    if _parse(receipt.get("generated_at")) is None:
        p.append("generated_at must be a real, parseable UTC timestamp")
    aa = receipt.get("attesting_authority")
    if not isinstance(aa, dict) or set(aa) != {"identity", "role", "key_id"} or not all(isinstance(aa[k], str) and aa[k] for k in aa):
        p.append("attesting_authority must be an object with non-empty identity/role/key_id strings")
    if not isinstance(receipt.get("signature"), str) or not receipt["signature"]:
        p.append("signature must be a non-empty string")
    return p


def receipt_signing_bytes(receipt: dict) -> bytes:
    """Canonical bytes the receipt's signature covers -- every field EXCEPT `signature` itself, mirroring
    corpus_generation_authorization.canonical_signing_bytes() / corpus_manifest.manifest_signing_bytes() exactly."""
    body = {k: v for k, v in receipt.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


def verify_receipt_signature(receipt: dict, keys: list) -> str | None:
    """Returns None if the receipt's signature is genuinely valid AND from a registered, active OWNER authority
    key present in `keys`; else a reason string. Never raises. Mirrors
    corpus_generation_authorization.verify_signature() / corpus_manifest.verify_manifest_signature() exactly."""
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except Exception:
        return "SIGNATURE_VERIFIER_UNAVAILABLE"
    aa = receipt.get("attesting_authority") or {}
    if not isinstance(aa, dict):
        return "MALFORMED_ATTESTING_AUTHORITY"
    key = next((k for k in keys if isinstance(k, dict) and k.get("key_id") == aa.get("key_id")), None)
    if key is None:
        return "AUTHORITY_KEY_NOT_REGISTERED"
    if key.get("role") != "OWNER" or key.get("role") != aa.get("role") or key.get("identity") != aa.get("identity"):
        return "AUTHORITY_NOT_OWNER_OR_IDENTITY_MISMATCH"
    try:
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(key["public_key_hex"]))
        pub.verify(bytes.fromhex(str(receipt.get("signature") or "")), receipt_signing_bytes(receipt))
    except InvalidSignature:
        return "INVALID_SIGNATURE"
    except Exception as e:
        return f"SIGNATURE_CHECK_ERROR:{type(e).__name__}"
    return None


def window_problems(receipt: dict, authorization_record: dict) -> list:
    """Item 1: `receipt.generated_at` must fall within the AUTHORIZATION's OWN `issued_at`/`expires_at` window --
    never compared against the current verification-time clock, which could be long after generation actually
    happened. Preserves `verify_referenced()`'s property that an authentic historical CGA can still be audited
    after its own window has elapsed -- THIS check is what actually proves generation happened in-window, not the
    CGA's own (deliberately window-agnostic) authentication."""
    gen_at = _parse(receipt.get("generated_at"))
    issued = _parse(authorization_record.get("issued_at"))
    expires = _parse(authorization_record.get("expires_at"))
    if gen_at is None:
        return ["IMPOSSIBLE_GENERATED_AT_TIMESTAMP"]
    if issued is None or expires is None:
        return ["AUTHORIZATION_WINDOW_UNPARSEABLE"]
    p = []
    if gen_at < issued:
        p.append("GENERATED_AT_BEFORE_AUTHORIZATION_ISSUED")
    if gen_at > expires:
        p.append("GENERATED_AT_AFTER_AUTHORIZATION_EXPIRED")
    return p


def binding_problems(receipt: dict, *, authorization_record: dict, manifest: dict, expected_corpus_digest: str,
                      requested_eval_version: str) -> list:
    """Item 2: exact agreement between the receipt and every OTHER already-authenticated object (the CGA, the
    manifest, and the actual receiving request) -- never trusts the receipt's own claims about identity in
    isolation. Every mismatch here must be caught BEFORE any private-split read or ledger grant."""
    p = []
    if receipt.get("corpus_generation_authorization_id") != authorization_record.get("authorization_id"):
        p.append("receipt.corpus_generation_authorization_id does not match the authenticated CGA's authorization_id")
    if receipt.get("corpus_id") != manifest.get("corpus_id"):
        p.append("receipt.corpus_id does not match the signed manifest's corpus_id")
    if receipt.get("eval_version") != requested_eval_version:
        p.append("receipt.eval_version does not match the receiving request's eval_version")
    if receipt.get("corpus_digest") != expected_corpus_digest:
        p.append("receipt.corpus_digest does not match the digest derived from the signed manifest")
    if receipt.get("generator_code_tree_sha256") != manifest.get("generator_code_sha256"):
        p.append("receipt.generator_code_tree_sha256 does not match the signed manifest's generator_code_sha256")
    if receipt.get("generator_code_tree_sha256") != authorization_record.get("authorized_code_tree_sha256"):
        p.append("receipt.generator_code_tree_sha256 does not match the authenticated CGA's authorized_code_tree_sha256")
    if receipt.get("generating_commit_sha") != manifest.get("generated_at_commit_sha"):
        p.append("receipt.generating_commit_sha does not match the signed manifest's generated_at_commit_sha")
    return p


def verify_receipt(receipt: dict, *, authorization_record: dict, manifest: dict, expected_corpus_digest: str,
                    requested_eval_version: str, authority_keys: list) -> list:
    """Composes structural validation, cryptographic signature authentication, cross-binding against the OTHER
    already-authenticated objects, and the authorization-window check -- in that exact order, fail-closed at each
    step (a structurally invalid or unsigned receipt is rejected before its claimed bindings are even compared).
    Never raises; a non-empty return means the receipt is NOT trusted."""
    try:
        return _verify_receipt_inner(receipt, authorization_record=authorization_record, manifest=manifest,
                                      expected_corpus_digest=expected_corpus_digest, requested_eval_version=requested_eval_version,
                                      authority_keys=authority_keys)
    except Exception as e:
        return [f"UNEXPECTED_VERIFY_RECEIPT_ERROR:{type(e).__name__}"]


def _verify_receipt_inner(receipt, *, authorization_record, manifest, expected_corpus_digest, requested_eval_version,
                           authority_keys) -> list:
    problems = validate_receipt(receipt)
    if problems:
        return problems
    sig_problem = verify_receipt_signature(receipt, authority_keys)
    if sig_problem:
        return [f"SIGNATURE_INVALID:{sig_problem}"]
    binding = binding_problems(receipt, authorization_record=authorization_record, manifest=manifest,
                                expected_corpus_digest=expected_corpus_digest, requested_eval_version=requested_eval_version)
    if binding:
        return binding
    return window_problems(receipt, authorization_record)
