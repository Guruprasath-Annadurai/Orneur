"""Candidate-lineage attestation: the mechanism a candidate model's training-provenance disclosure must satisfy before
it can be exempted from the fail-closed "uncertain exposure ⇒ exclude or require a fresh lineage" rule in
GENESIS_V2_UNAVAILABLE_CORPUS_ACCEPTANCE_POLICY.json. No candidate exists yet; this module only validates the shape
of an attestation and derives the resulting qualification eligibility — it never asserts a candidate IS clean.

Evidence requirements (never satisfied by a bare self-declaration):
  - A DISCLOSED_CLEAN claim needs a reproducible training-log digest AND a real, cryptographically verified signature
    from a REGISTERED reviewer (`reviewer_registry.py`, role `PRIVATE_BENCHMARK_REVIEWER` — the SAME registry this
    program already uses for corpus-inventory review authority; this is not a separate, invented trust root). A
    self-declared boolean ("confirms_log_digest: true") is never accepted — schema /2 had exactly that self-declared
    metadata weakness and is replaced here by an actual Ed25519 signature verified against an active, registered
    reviewer key, the same way every other signed record in this program is verified.
  - The attestation binds to a specific `candidate_revision` — a disclosure about "the model" in general, not a
    named, pinned revision, is not eligibility evidence for any specific candidate run.
  - `exposure_to_unresolved_corpora.unresolved_classes_considered` must be checked against the REAL, current set of
    unresolved corpus classes (`historical_exposure_complete()`, cross-referencing the live signed inventory) — a
    self-reported "considered" list that omits a real unresolved class is not trusted.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

SCHEMA_VERSION = "genesis-v2-candidate-lineage-attestation/3"
EXPOSURE_STATES = ("UNDISCLOSED", "DISCLOSED_UNCERTAIN", "DISCLOSED_CLEAN")
REQUIRED_FIELDS = frozenset({"schema_version", "candidate_id", "candidate_revision", "model_family", "attested_by",
                             "attestation_timestamp", "training_data_disclosure_source", "reproducible_training_log_digest",
                             "independent_verification", "exposure_to_unresolved_corpora", "notes"})
_VERIFICATION_FIELDS = frozenset({"verifier_identity", "verification_method", "verified_at", "signature"})
_SHA64 = re.compile(r"^[0-9a-f]{64}$")
_SIG128 = re.compile(r"^[0-9a-f]{128}$")
_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def verification_signing_bytes(rec: dict) -> bytes:
    """The exact canonical bytes the reviewer signs: binds the signature to THIS candidate/revision/log-digest/
    verifier tuple, not just a bare "yes" floating free of what was actually reviewed."""
    iv = rec.get("independent_verification") or {}
    body = {"candidate_id": rec.get("candidate_id"), "candidate_revision": rec.get("candidate_revision"),
            "reproducible_training_log_digest": rec.get("reproducible_training_log_digest"),
            "verifier_identity": iv.get("verifier_identity"), "verification_method": iv.get("verification_method"),
            "verified_at": iv.get("verified_at")}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


def validate_attestation(rec) -> list:
    p = []
    if not isinstance(rec, dict):
        return ["record is not an object"]
    if set(rec) != REQUIRED_FIELDS:
        return [f"schema mismatch: expected {sorted(REQUIRED_FIELDS)}, got {sorted(rec)}"]
    if rec["schema_version"] != SCHEMA_VERSION:
        p.append("schema_version mismatch")
    for f in ("candidate_id", "candidate_revision", "model_family", "attested_by"):
        if not isinstance(rec[f], str) or not rec[f]:
            p.append(f"{f} required")
    if not isinstance(rec["attestation_timestamp"], str) or not _TS.match(rec["attestation_timestamp"]):
        p.append("attestation_timestamp invalid")
    if rec["training_data_disclosure_source"] is not None and not isinstance(rec["training_data_disclosure_source"], str):
        p.append("training_data_disclosure_source must be null or a string (URL/document reference)")
    if rec["reproducible_training_log_digest"] is not None and not (
            isinstance(rec["reproducible_training_log_digest"], str) and _SHA64.match(rec["reproducible_training_log_digest"])):
        p.append("reproducible_training_log_digest must be null or a sha256 hex digest")
    iv = rec.get("independent_verification")
    if iv is not None:
        if not isinstance(iv, dict) or set(iv) != _VERIFICATION_FIELDS:
            p.append(f"independent_verification must be null or an object with exactly {sorted(_VERIFICATION_FIELDS)}")
        else:
            if not isinstance(iv.get("verifier_identity"), str) or not iv["verifier_identity"]:
                p.append("independent_verification.verifier_identity required")
            if not isinstance(iv.get("verification_method"), str) or not iv["verification_method"]:
                p.append("independent_verification.verification_method required")
            if not isinstance(iv.get("verified_at"), str) or not _TS.match(iv["verified_at"]):
                p.append("independent_verification.verified_at invalid")
            if not (isinstance(iv.get("signature"), str) and _SIG128.match(iv["signature"])):
                p.append("independent_verification.signature must be a 128-hex-char Ed25519 signature — not a bare boolean claim")
            if isinstance(iv.get("verifier_identity"), str) and iv["verifier_identity"] == rec.get("attested_by"):
                p.append("independent_verification.verifier_identity must differ from attested_by (not independent otherwise)")
    exposure = rec.get("exposure_to_unresolved_corpora")
    if not isinstance(exposure, dict) or not isinstance(exposure.get("state"), str) or exposure["state"] not in EXPOSURE_STATES:
        p.append(f"exposure_to_unresolved_corpora.state must be one of {EXPOSURE_STATES}")
    elif not isinstance(exposure.get("unresolved_classes_considered"), list):
        p.append("exposure_to_unresolved_corpora.unresolved_classes_considered must be a list")
    if not isinstance(rec["notes"], str):
        p.append("notes must be a string (may be empty, never absent)")
    return p


def verify_reviewer_signature(rec: dict, reviewer_keys: list | None) -> str | None:
    """Returns None if the independent_verification signature verifies against an ACTIVE, registered reviewer key
    (role PRIVATE_BENCHMARK_REVIEWER, from reviewer_registry.active_reviewer_keys — the SAME registry
    corpus-inventory review already uses), else a reason string. Never raises. `reviewer_keys is None` (no registry
    supplied) always fails closed — this mirrors inventory.validate_attestation_record's own "no keys => not
    verified" default."""
    iv = rec.get("independent_verification")
    if not isinstance(iv, dict):
        return "NO_INDEPENDENT_VERIFICATION"
    if reviewer_keys is None:
        return "REVIEWER_SIGNATURE_NOT_VERIFIED: no reviewer-key registry supplied"
    key = next((k for k in reviewer_keys if isinstance(k, dict) and k.get("identity") == iv.get("verifier_identity")
                and k.get("role") == "PRIVATE_BENCHMARK_REVIEWER"), None)
    if key is None:
        return "REVIEWER_SIGNATURE_NOT_VERIFIED: verifier_identity is not a registered, active PRIVATE_BENCHMARK_REVIEWER key"
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(key["public_key_hex"])).verify(
            bytes.fromhex(iv["signature"]), verification_signing_bytes(rec))
    except InvalidSignature:
        return "REVIEWER_SIGNATURE_NOT_VERIFIED: invalid signature"
    except Exception as e:
        return f"REVIEWER_SIGNATURE_NOT_VERIFIED: {type(e).__name__}"
    return None


def historical_exposure_complete(rec: dict, root) -> tuple:
    """(complete: bool, missing: list). Cross-checks unresolved_classes_considered against the REAL, current set of
    unresolved classes derived directly from the live signed inventory — never trusts the attestation's own list as
    complete just because it is well-formed."""
    from orca.eval.genesis_v2 import inventory as INV
    inv = json.loads((Path(root) / INV.INVENTORY_PATH).read_text())
    real_unresolved = INV.actually_unavailable_classes(inv)
    considered = set((rec.get("exposure_to_unresolved_corpora") or {}).get("unresolved_classes_considered") or [])
    missing = sorted(real_unresolved - considered)
    return (not missing), missing


def qualification_eligibility(rec: dict, *, root=None, reviewer_keys: list | None = None) -> dict:
    """Derives what the fail-closed acceptance-policy rule (see GENESIS_V2_UNAVAILABLE_CORPUS_ACCEPTANCE_POLICY.json)
    means for THIS candidate. Never returns an eligibility claim for a structurally invalid record, an unverified
    disclosure, or an attestation that omits a currently-real unresolved corpus class. `root` is required to check
    historical-exposure completeness against the live inventory. `reviewer_keys` is required (active
    PRIVATE_BENCHMARK_REVIEWER keys from reviewer_registry.py) to verify the independent verification's signature —
    omitting either means the corresponding check cannot pass, by design."""
    problems = validate_attestation(rec)
    if problems:
        return {"eligible": False, "reason": "INVALID_ATTESTATION", "problems": problems}
    state = rec["exposure_to_unresolved_corpora"]["state"]
    if state != "DISCLOSED_CLEAN":
        reason = "UNCERTAIN_EXPOSURE_REQUIRES_EXCLUSION_OR_FRESH_LINEAGE" if state == "DISCLOSED_UNCERTAIN" else "UNDISCLOSED_TREATED_AS_UNCERTAIN"
        return {"eligible": False, "reason": reason, "problems": []}
    if not rec["reproducible_training_log_digest"]:
        return {"eligible": False, "reason": "CLEAN_CLAIM_WITHOUT_VERIFIABLE_LOG", "problems": []}
    sig_problem = verify_reviewer_signature(rec, reviewer_keys)
    if sig_problem:
        return {"eligible": False, "reason": "CLEAN_CLAIM_WITHOUT_INDEPENDENT_VERIFICATION", "problems": [sig_problem]}
    if root is None:
        return {"eligible": False, "reason": "HISTORICAL_EXPOSURE_COMPLETENESS_NOT_CHECKED", "problems": []}
    complete, missing = historical_exposure_complete(rec, root)
    if not complete:
        return {"eligible": False, "reason": "UNRESOLVED_HISTORICAL_CLASS_NOT_CONSIDERED", "problems": [{"missing_class": c} for c in missing]}
    return {"eligible": True, "reason": "DISCLOSED_CLEAN_INDEPENDENTLY_VERIFIED_AND_EXPOSURE_COMPLETE", "problems": []}
