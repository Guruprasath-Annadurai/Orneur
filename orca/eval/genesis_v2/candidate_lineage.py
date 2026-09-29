"""Candidate-lineage attestation: the mechanism a candidate model's training-provenance disclosure must satisfy before
it can be exempted from the fail-closed "uncertain exposure ⇒ exclude or require a fresh lineage" rule in
GENESIS_V2_UNAVAILABLE_CORPUS_ACCEPTANCE_POLICY.json. No candidate exists yet; this module only validates the shape
of an attestation and derives the resulting qualification eligibility — it never asserts a candidate IS clean.

Evidence requirements (never satisfied by a bare self-declaration):
  - A DISCLOSED_CLEAN claim needs a reproducible training-log digest AND a genuinely INDEPENDENT verification of that
    digest — someone other than the party making the disclosure (`independent_verification.verifier_identity` must
    differ from `attested_by`, and its role must be exactly INDEPENDENT_OF_CANDIDATE_PROVIDER) who actually confirms
    it (`confirms_log_digest: true`). A syntactically valid 64-hex digest with no independent confirmation is treated
    exactly like no digest at all.
  - The attestation binds to a specific `candidate_revision` — a disclosure about "the model" in general, not a
    named, pinned revision, is not eligibility evidence for any specific candidate run.
  - `exposure_to_unresolved_corpora.unresolved_classes_considered` must be checked against the REAL, current set of
    unresolved corpus classes (`historical_exposure_complete()`, cross-referencing the live signed inventory) — a
    self-reported "considered" list that omits a real unresolved class is not trusted; eligibility requires the
    attestation to have genuinely considered every class the inventory currently flags as unresolved.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

SCHEMA_VERSION = "genesis-v2-candidate-lineage-attestation/2"
EXPOSURE_STATES = ("UNDISCLOSED", "DISCLOSED_UNCERTAIN", "DISCLOSED_CLEAN")
VERIFIER_ROLES = ("INDEPENDENT_OF_CANDIDATE_PROVIDER",)
REQUIRED_FIELDS = frozenset({"schema_version", "candidate_id", "candidate_revision", "model_family", "attested_by",
                             "attestation_timestamp", "training_data_disclosure_source", "reproducible_training_log_digest",
                             "independent_verification", "exposure_to_unresolved_corpora", "notes"})
_VERIFICATION_FIELDS = frozenset({"verifier_identity", "verifier_role", "verification_method", "verified_at", "confirms_log_digest"})
_SHA64 = re.compile(r"^[0-9a-f]{64}$")
_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


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
            if iv.get("verifier_role") not in VERIFIER_ROLES:
                p.append(f"independent_verification.verifier_role must be one of {VERIFIER_ROLES}")
            if not isinstance(iv.get("verification_method"), str) or not iv["verification_method"]:
                p.append("independent_verification.verification_method required")
            if not isinstance(iv.get("verified_at"), str) or not _TS.match(iv["verified_at"]):
                p.append("independent_verification.verified_at invalid")
            if not isinstance(iv.get("confirms_log_digest"), bool):
                p.append("independent_verification.confirms_log_digest must be a boolean")
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


def qualification_eligibility(rec: dict, *, root=None) -> dict:
    """Derives what the fail-closed acceptance-policy rule (see GENESIS_V2_UNAVAILABLE_CORPUS_ACCEPTANCE_POLICY.json)
    means for THIS candidate. Never returns an eligibility claim for a structurally invalid record, an unverified
    disclosure, or an attestation that omits a currently-real unresolved corpus class. `root` is required to check
    historical-exposure completeness against the live inventory; omitting it means that check cannot pass."""
    problems = validate_attestation(rec)
    if problems:
        return {"eligible": False, "reason": "INVALID_ATTESTATION", "problems": problems}
    state = rec["exposure_to_unresolved_corpora"]["state"]
    if state != "DISCLOSED_CLEAN":
        reason = "UNCERTAIN_EXPOSURE_REQUIRES_EXCLUSION_OR_FRESH_LINEAGE" if state == "DISCLOSED_UNCERTAIN" else "UNDISCLOSED_TREATED_AS_UNCERTAIN"
        return {"eligible": False, "reason": reason, "problems": []}
    if not rec["reproducible_training_log_digest"]:
        return {"eligible": False, "reason": "CLEAN_CLAIM_WITHOUT_VERIFIABLE_LOG", "problems": []}
    iv = rec.get("independent_verification")
    if not iv or iv.get("confirms_log_digest") is not True:
        return {"eligible": False, "reason": "CLEAN_CLAIM_WITHOUT_INDEPENDENT_VERIFICATION", "problems": []}
    if root is None:
        return {"eligible": False, "reason": "HISTORICAL_EXPOSURE_COMPLETENESS_NOT_CHECKED", "problems": []}
    complete, missing = historical_exposure_complete(rec, root)
    if not complete:
        return {"eligible": False, "reason": "UNRESOLVED_HISTORICAL_CLASS_NOT_CONSIDERED", "problems": [{"missing_class": c} for c in missing]}
    return {"eligible": True, "reason": "DISCLOSED_CLEAN_INDEPENDENTLY_VERIFIED_AND_EXPOSURE_COMPLETE", "problems": []}
