"""Genesis training / adaptation corpus inventory: the deterministic contract that lets contamination checks know EVERY corpus that may have
influenced Genesis before qualification. Fail closed: an empty, unattested, partially unavailable or unresolved inventory is never PASS.

Location kinds: REPO_PATH (relative to the repository root), ORCA_HOME_PATH (relative to the owner's ORCA_HOME; machine-local, absent on CI),
EXTERNAL_DESCRIPTOR (a description only, e.g. a dataset uploaded to an external service; never resolvable here => UNAVAILABLE).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from orca.eval.genesis_v2 import contamination as C

INVENTORY_PATH = "docs/orneur/phase-21/GENESIS_TRAINING_AND_ADAPTATION_CORPUS_INVENTORY.json"
SCHEMA_VERSION = "genesis-corpus-inventory/1"

CORPUS_CLASSES = (
    "public_sft_datasets", "private_sft_datasets", "instruction_tuning_datasets", "reasoning_datasets", "coding_datasets", "tool_use_datasets",
    "preference_dpo_data", "rlhf_rlaif_data", "synthetic_generation_corpora", "distillation_data", "evaluation_derived_adaptation_data",
    "prompt_tuning_few_shot_stores", "retrieval_corpora", "router_expert_training_data", "future_fine_tuning_datasets",
    "manually_authored_internal_examples", "candidate_specific_adaptation_sets", "public_benchmark_v1", "public_pilot_train_v1", "external_uploaded_datasets")
STATUSES = ("PRESENT", "DECLARED_NOT_PRESENT", "UNAVAILABLE", "RETIRED")
CLASSIFICATIONS = ("PUBLIC", "PRIVATE")
LOCATION_KINDS = ("REPO_PATH", "ORCA_HOME_PATH", "EXTERNAL_DESCRIPTOR")
CHECK_STATUSES = ("PENDING_V2_CORPUS", "PASS", "FAIL", "UNAVAILABLE")
COVERAGE = ("LISTED", "NONE_KNOWN_UNATTESTED", "NONE_DECLARED_OWNER_REVIEWED", "NONE_EXIST_ATTESTED")
# NONE_DECLARED_OWNER_REVIEWED: the owner has genuinely reviewed and found no corpora of this class, but the inventory's overall
# completeness_attestation is not yet a signed ATTESTED record. NONE_EXIST_ATTESTED is a stronger claim ("...ATTESTED") and is only a
# valid declaration once completeness_attestation.status == "ATTESTED" with a verified owner signature (see validate() below) — using
# ATTESTED-sounding terminology before a real signature exists is exactly the premature-terminology failure this distinction prevents.
TRISTATE_FIELDS = ("used_in_training", "used_in_adaptation", "visible_during_screen", "visible_during_qualification_holdout")

CORPUS_REQUIRED = ("corpus_id", "version", "corpus_class", "purpose", "provenance", "classification", "storage", "manifest_id_or_sha256", "record_count",
                   *TRISTATE_FIELDS, "permitted_lifecycle", "contamination_check_status", "owner", "status")


def empty_inventory() -> dict:
    return {"document": "GENESIS_TRAINING_AND_ADAPTATION_CORPUS_INVENTORY", "schema_version": SCHEMA_VERSION, "inventory_version": "1",
            "completeness_attestation": {"status": "NOT_ATTESTED", "record": None},
            "class_coverage": {c: {"declaration": "NONE_KNOWN_UNATTESTED", "corpus_ids": []} for c in CORPUS_CLASSES}, "corpora": [], "excluded_artifacts": []}


ATTESTATION_VERDICTS = ("COMPLETE", "INCOMPLETE", "COMPLETE_WITH_DECLARED_UNAVAILABLE")
ATTESTATION_SCHEMA_VERSION = "genesis-v2-corpus-inventory-attestation/1"


def attestation_signing_bytes(att: dict) -> bytes:
    import json as _json
    return _json.dumps({k: v for k, v in att.items() if k != "signature"}, sort_keys=True, separators=(",", ":")).encode()


def validate_attestation_record(att, inventory_digest: str, *, authority_keys: list | None = None) -> list:
    """Full owner-attestation schema: inventory version, corpus inventory digest, owner identity, review timestamp, scope reviewed, unresolved
    classes, completeness status, signature, schema version. A signature is verified against a registered OWNER-role authority key when
    `authority_keys` is supplied; without a valid signature, an attestation can never make contamination_controls_pass true."""
    p = []
    if not isinstance(att, dict):
        return ["attestation is not an object"]
    required = {"schema_version", "inventory_version", "corpus_inventory_digest", "owner_identity", "review_timestamp", "scope_reviewed",
                "unresolved_classes", "completeness_status", "signature"}
    if set(att) != required:
        return [f"attestation schema mismatch: expected {sorted(required)}"]
    if att["schema_version"] != ATTESTATION_SCHEMA_VERSION:
        p.append("attestation schema_version mismatch")
    if att["corpus_inventory_digest"] != inventory_digest:
        p.append("corpus_inventory_digest does not match this inventory")
    if att["completeness_status"] not in ATTESTATION_VERDICTS:
        p.append(f"completeness_status must be one of {ATTESTATION_VERDICTS}")
    if not isinstance(att["unresolved_classes"], list):
        p.append("unresolved_classes must be a list")
    elif att["completeness_status"] == "COMPLETE" and att["unresolved_classes"]:
        p.append("completeness_status=COMPLETE is inconsistent with a non-empty unresolved_classes list")
    if not att.get("owner_identity"):
        p.append("owner_identity required")
    if authority_keys is None:
        p.append("SIGNATURE_NOT_VERIFIED: no authority-key registry supplied")
    else:
        sig = att.get("signature")
        key = next((k for k in authority_keys if k.get("identity") == att.get("owner_identity") and k.get("role") == "OWNER"), None)
        if key is None:
            p.append("SIGNATURE_NOT_VERIFIED: owner_identity is not a registered, active OWNER authority key")
        else:
            try:
                from cryptography.exceptions import InvalidSignature
                from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
                Ed25519PublicKey.from_public_bytes(bytes.fromhex(key["public_key_hex"])).verify(bytes.fromhex(str(sig)), attestation_signing_bytes(att))
            except Exception:
                p.append("SIGNATURE_NOT_VERIFIED: invalid signature")
    return p


def inventory_digest(inv: dict) -> str:
    import hashlib as _h
    import json as _json
    body = {k: v for k, v in inv.items() if k not in ("completeness_attestation",)}
    return _h.sha256(_json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate(inv, *, authority_keys: list | None = None) -> list:
    p = []
    if not isinstance(inv, dict) or inv.get("schema_version") != SCHEMA_VERSION:
        return ["inventory missing or wrong schema_version"]
    att = inv.get("completeness_attestation")
    if not isinstance(att, dict) or att.get("status") not in ("NOT_ATTESTED", "ATTESTED"):
        p.append("completeness_attestation.status invalid")
    elif att["status"] == "ATTESTED":
        record = att.get("record")
        if not isinstance(record, dict):
            p.append("an ATTESTED status requires an attestation record")
        else:
            p += validate_attestation_record(record, inventory_digest(inv), authority_keys=authority_keys)
    ids = set()
    for i, c in enumerate(inv.get("corpora") or []):
        if not isinstance(c, dict):
            p.append(f"corpora[{i}] not an object")
            continue
        miss = [k for k in CORPUS_REQUIRED if k not in c]
        if miss:
            p.append(f"{c.get('corpus_id', i)}: missing {miss}")
            continue
        if c["corpus_id"] in ids:
            p.append(f"duplicate corpus_id {c['corpus_id']}")
        ids.add(c["corpus_id"])
        if c["corpus_class"] not in CORPUS_CLASSES:
            p.append(f"{c['corpus_id']}: unknown class")
        if c["status"] not in STATUSES:
            p.append(f"{c['corpus_id']}: bad status")
        if c["classification"] not in CLASSIFICATIONS:
            p.append(f"{c['corpus_id']}: bad classification")
        if c["contamination_check_status"] not in CHECK_STATUSES:
            p.append(f"{c['corpus_id']}: bad contamination_check_status")
        st = c["storage"]
        if not (isinstance(st, dict) and st.get("kind") in LOCATION_KINDS and st.get("location")):
            p.append(f"{c['corpus_id']}: bad storage descriptor")
        for f in TRISTATE_FIELDS:
            if c[f] not in (True, False, "UNKNOWN"):
                p.append(f"{c['corpus_id']}: {f} must be true/false/UNKNOWN")
        if c["record_count"] is not None and (not isinstance(c["record_count"], int) or isinstance(c["record_count"], bool) or c["record_count"] < 0):
            p.append(f"{c['corpus_id']}: bad record_count")
        if c["status"] == "PRESENT" and not (isinstance(c["manifest_id_or_sha256"], str) and len(c["manifest_id_or_sha256"]) == 64):
            p.append(f"{c['corpus_id']}: a PRESENT corpus needs a sha256")
    attested = isinstance(att, dict) and att.get("status") == "ATTESTED"
    cov = inv.get("class_coverage")
    if not isinstance(cov, dict) or set(cov) != set(CORPUS_CLASSES):
        p.append("class_coverage must cover every corpus class")
    else:
        for cls, e in cov.items():
            if e.get("declaration") not in COVERAGE:
                p.append(f"{cls}: bad coverage declaration")
            elif e["declaration"] == "NONE_EXIST_ATTESTED" and not attested:
                p.append(f"{cls}: NONE_EXIST_ATTESTED requires a signed ATTESTED completeness_attestation; use NONE_DECLARED_OWNER_REVIEWED until then")
            elif e["declaration"] == "LISTED":
                listed = {c.get("corpus_id") for c in inv["corpora"] if c.get("corpus_class") == cls}
                if not listed or set(e.get("corpus_ids", [])) != listed:
                    p.append(f"{cls}: LISTED coverage does not match the corpora of that class")
            elif any(c.get("corpus_class") == cls for c in inv["corpora"]):
                p.append(f"{cls}: corpora exist but coverage is not LISTED")
    return p


def _resolve(entry: dict, root: Path, orca_home: Path | None):
    st = entry["storage"]
    if st["kind"] == "REPO_PATH":
        return Path(root) / st["location"]
    if st["kind"] == "ORCA_HOME_PATH" and orca_home is not None:
        return Path(orca_home) / st["location"]
    return None


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def evaluate_pre_corpus_attestation(inv, *, authority_keys: list | None = None, acceptance_policy: dict | None = None) -> C.CheckResult:
    """A DIFFERENT, NARROWER question than evaluate(): is the owner's SIGNED completeness attestation itself valid — real OWNER
    signature, exact inventory-digest binding, every class declared, and (if the owner declared some class unresolved) that
    declaration covered by a frozen, pre-corpus-independent acceptance policy?

    This deliberately does NOT resolve any corpus file on disk, check content hashes, or require per-corpus
    contamination_check_status == PASS — those are properties of the (nonexistent, pre-corpus) V2 candidate comparison, not of the
    attestation. Requiring them here would make corpus_inventory_attested_pass structurally impossible to satisfy before the private
    corpus exists (a stage-boundary defect), while contributing nothing to catching a dishonest or unsigned attestation.

    Full contamination qualification (evaluate(), below) is UNCHANGED and remains fail-closed: it still requires every source file
    resolvable, hash-verified, and PASS contamination_check_status, and correctly never reaches PASS before a V2 corpus exists to
    compare against. That is a separate, later-stage question this function does not answer or weaken."""
    name = "corpus_inventory_pre_corpus_attestation"
    problems = validate(inv, authority_keys=authority_keys)     # structural + signature validity only; never touches the filesystem
    if problems:
        return C.CheckResult(name, C.FAIL, [{"problem": p} for p in problems[:20]], "inventory or attestation schema/signature invalid")
    att = inv["completeness_attestation"]
    if att.get("status") != "ATTESTED":
        return C.CheckResult(name, C.INCOMPLETE, [], "completeness_attestation is not yet a signed ATTESTED record")
    gaps = [{"class": k, "declaration": v["declaration"]} for k, v in inv["class_coverage"].items() if v["declaration"] == "NONE_KNOWN_UNATTESTED"]
    if gaps:
        return C.CheckResult(name, C.INCOMPLETE, gaps, "per-class coverage gaps remain (a class was never reviewed)")
    record = att["record"]
    verdict = record.get("completeness_status")
    if verdict not in ("COMPLETE", "COMPLETE_WITH_DECLARED_UNAVAILABLE"):
        return C.CheckResult(name, C.INCOMPLETE, [], f"attestation completeness_status={verdict!r} is not an acceptable pre-corpus verdict")
    unresolved = record.get("unresolved_classes") or []
    if verdict == "COMPLETE_WITH_DECLARED_UNAVAILABLE":
        if not unresolved:
            return C.CheckResult(name, C.FAIL, [], "COMPLETE_WITH_DECLARED_UNAVAILABLE with an empty unresolved_classes list is inconsistent")
        if not isinstance(acceptance_policy, dict) or not acceptance_policy.get("frozen"):
            return C.CheckResult(name, C.INCOMPLETE, [{"unresolved_classes": unresolved}], "no frozen unavailable-corpus acceptance policy supplied")
        covered = set(acceptance_policy.get("applies_to_unresolved_classes") or [])
        missing = [c for c in unresolved if c not in covered]
        if missing:
            return C.CheckResult(name, C.FAIL, [{"uncovered_class": c} for c in missing],
                                  "unresolved class(es) declared in the attestation are not covered by the frozen acceptance policy")
    return C.CheckResult(name, C.PASS, [], f"signed OWNER attestation valid: completeness_status={verdict}, unresolved={unresolved}")


def evaluate(inv, root: Path, orca_home: Path | None = None, *, authority_keys: list | None = None) -> C.CheckResult:
    """The fail-closed verdict on inventory completeness for contamination purposes."""
    name = "training_corpora_inventory"
    p = validate(inv, authority_keys=authority_keys)
    if p:
        return C.CheckResult(name, C.FAIL, [{"problem": x} for x in p[:20]], "inventory schema violations")
    corpora = inv["corpora"]
    if not corpora:
        return C.CheckResult(name, C.INCOMPLETE, [], "empty inventory: an empty inventory never means PASS")
    unavailable, unresolved, mism = [], [], []
    for c in corpora:
        if c["status"] == "RETIRED":
            continue
        if c["status"] in ("UNAVAILABLE", "DECLARED_NOT_PRESENT"):
            unavailable.append({"corpus": c["corpus_id"], "why": c["status"]})
            continue
        path = _resolve(c, root, orca_home)
        if path is None or not path.is_file():
            unavailable.append({"corpus": c["corpus_id"], "why": "NOT_RESOLVABLE_IN_THIS_ENVIRONMENT"})
            continue
        if _sha(path) != c["manifest_id_or_sha256"]:
            mism.append({"corpus": c["corpus_id"], "why": "HASH_MISMATCH"})
        for f in TRISTATE_FIELDS:
            if c[f] == "UNKNOWN":
                unresolved.append({"corpus": c["corpus_id"], "field": f})
        if c["contamination_check_status"] != "PASS":
            unresolved.append({"corpus": c["corpus_id"], "field": "contamination_check_status", "value": c["contamination_check_status"]})
    if mism:
        return C.CheckResult(name, C.FAIL, mism, "a PRESENT corpus no longer matches its recorded hash")
    if unavailable:
        return C.CheckResult(name, C.DATASET_UNAVAILABLE, unavailable, "unresolved UNAVAILABLE / not-present / non-resolvable sources")
    gaps = [{"class": k, "declaration": v["declaration"]} for k, v in inv["class_coverage"].items() if v["declaration"] == "NONE_KNOWN_UNATTESTED"]
    att = inv["completeness_attestation"]
    verdict = (att.get("record") or {}).get("completeness_status") if att.get("status") == "ATTESTED" else None
    if att.get("status") != "ATTESTED" or verdict not in ("COMPLETE", "COMPLETE_WITH_DECLARED_UNAVAILABLE") or gaps:
        return C.CheckResult(name, C.INCOMPLETE, gaps, "completeness not signed-attested by a registered OWNER authority as COMPLETE / COMPLETE_WITH_DECLARED_UNAVAILABLE, or per-class coverage gaps remain")
    if unresolved:
        return C.CheckResult(name, C.INCOMPLETE, unresolved, "unresolved usage/visibility flags or contamination checks not PASS")
    return C.CheckResult(name, C.PASS, [], f"{len(corpora)} corpora inventoried, resolved, hash-verified and attested complete")


def sources(inv: dict, root: Path, orca_home: Path | None, *, text_key: str = "text") -> tuple:
    """(sources dict for check_training_corpora, required names). Only PRESENT, resolvable JSONL corpora."""
    src, req = {}, []
    for c in inv["corpora"]:
        if c["status"] != "PRESENT":
            continue
        path = _resolve(c, root, orca_home)
        if path is not None and path.suffix == ".jsonl":
            src[c["corpus_id"]] = C.FileTrainingCorpus(c["corpus_id"], path, text_key)
            req.append(c["corpus_id"])
    return src, tuple(req)


def check_v2_against_inventory(v2_items: list, inv: dict, root: Path, orca_home: Path | None = None) -> list:
    """Inventory completeness FIRST; overlap comparison only when the inventory is trustworthy. Never PASS on an incomplete inventory."""
    inv_res = evaluate(inv, root, orca_home)
    if inv_res.status != C.PASS:
        return [C.CheckResult("training_corpora", inv_res.status if inv_res.status != C.PASS else C.INCOMPLETE, inv_res.findings, inv_res.note)]
    src, req = sources(inv, root, orca_home)
    return C.check_training_corpora(v2_items, src, required=req, declared_complete=True)
