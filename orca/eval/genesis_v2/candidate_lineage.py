"""Candidate-lineage attestation: the mechanism a candidate model's training-provenance disclosure must satisfy before
it can be exempted from the fail-closed "uncertain exposure ⇒ exclude or require a fresh lineage" rule in
GENESIS_V2_UNAVAILABLE_CORPUS_ACCEPTANCE_POLICY.json. No candidate exists yet; this module only validates the shape
of an attestation and derives the resulting qualification eligibility — it never asserts a candidate IS clean."""
from __future__ import annotations

import re

SCHEMA_VERSION = "genesis-v2-candidate-lineage-attestation/1"
EXPOSURE_STATES = ("UNDISCLOSED", "DISCLOSED_UNCERTAIN", "DISCLOSED_CLEAN")
REQUIRED_FIELDS = frozenset({"schema_version", "candidate_id", "model_family", "attested_by", "attestation_timestamp",
                             "training_data_disclosure_source", "reproducible_training_log_digest", "exposure_to_unresolved_corpora",
                             "notes"})
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
    for f in ("candidate_id", "model_family", "attested_by"):
        if not isinstance(rec[f], str) or not rec[f]:
            p.append(f"{f} required")
    if not isinstance(rec["attestation_timestamp"], str) or not _TS.match(rec["attestation_timestamp"]):
        p.append("attestation_timestamp invalid")
    if rec["training_data_disclosure_source"] is not None and not isinstance(rec["training_data_disclosure_source"], str):
        p.append("training_data_disclosure_source must be null or a string (URL/document reference)")
    if rec["reproducible_training_log_digest"] is not None and not (
            isinstance(rec["reproducible_training_log_digest"], str) and _SHA64.match(rec["reproducible_training_log_digest"])):
        p.append("reproducible_training_log_digest must be null or a sha256 hex digest")
    exposure = rec.get("exposure_to_unresolved_corpora")
    if not isinstance(exposure, dict) or not isinstance(exposure.get("state"), str) or exposure["state"] not in EXPOSURE_STATES:
        p.append(f"exposure_to_unresolved_corpora.state must be one of {EXPOSURE_STATES}")
    elif not isinstance(exposure.get("unresolved_classes_considered"), list):
        p.append("exposure_to_unresolved_corpora.unresolved_classes_considered must be a list")
    if not isinstance(rec["notes"], str):
        p.append("notes must be a string (may be empty, never absent)")
    return p


def qualification_eligibility(rec: dict) -> dict:
    """Derives what the fail-closed acceptance-policy rule (see GENESIS_V2_UNAVAILABLE_CORPUS_ACCEPTANCE_POLICY.json)
    means for THIS candidate. Never returns an eligibility claim for a structurally invalid record."""
    problems = validate_attestation(rec)
    if problems:
        return {"eligible": False, "reason": "INVALID_ATTESTATION", "problems": problems}
    state = rec["exposure_to_unresolved_corpora"]["state"]
    if state == "DISCLOSED_CLEAN":
        # Even a DISCLOSED_CLEAN claim requires a verifiable log digest — an unverifiable "trust me" disclosure is not
        # different in kind from UNDISCLOSED for this gate's purposes.
        if not rec["reproducible_training_log_digest"]:
            return {"eligible": False, "reason": "CLEAN_CLAIM_WITHOUT_VERIFIABLE_LOG", "problems": []}
        return {"eligible": True, "reason": "DISCLOSED_CLEAN_WITH_VERIFIABLE_LOG", "problems": []}
    if state == "DISCLOSED_UNCERTAIN":
        return {"eligible": False, "reason": "UNCERTAIN_EXPOSURE_REQUIRES_EXCLUSION_OR_FRESH_LINEAGE", "problems": []}
    return {"eligible": False, "reason": "UNDISCLOSED_TREATED_AS_UNCERTAIN", "problems": []}
