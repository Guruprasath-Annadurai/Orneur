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
COVERAGE = ("LISTED", "NONE_KNOWN_UNATTESTED", "NONE_EXIST_ATTESTED")
TRISTATE_FIELDS = ("used_in_training", "used_in_adaptation", "visible_during_screen", "visible_during_qualification_holdout")

CORPUS_REQUIRED = ("corpus_id", "version", "corpus_class", "purpose", "provenance", "classification", "storage", "manifest_id_or_sha256", "record_count",
                   *TRISTATE_FIELDS, "permitted_lifecycle", "contamination_check_status", "owner", "status")


def empty_inventory() -> dict:
    return {"document": "GENESIS_TRAINING_AND_ADAPTATION_CORPUS_INVENTORY", "schema_version": SCHEMA_VERSION, "inventory_version": "1",
            "completeness_attestation": {"status": "NOT_ATTESTED", "attested_by": None, "attested_at": None},
            "class_coverage": {c: {"declaration": "NONE_KNOWN_UNATTESTED", "corpus_ids": []} for c in CORPUS_CLASSES}, "corpora": [], "excluded_artifacts": []}


def validate(inv) -> list:
    p = []
    if not isinstance(inv, dict) or inv.get("schema_version") != SCHEMA_VERSION:
        return ["inventory missing or wrong schema_version"]
    att = inv.get("completeness_attestation")
    if not isinstance(att, dict) or att.get("status") not in ("NOT_ATTESTED", "ATTESTED_COMPLETE"):
        p.append("completeness_attestation.status invalid")
    elif att["status"] == "ATTESTED_COMPLETE" and not (att.get("attested_by") and att.get("attested_at")):
        p.append("an attested inventory must name who attested and when")
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
    cov = inv.get("class_coverage")
    if not isinstance(cov, dict) or set(cov) != set(CORPUS_CLASSES):
        p.append("class_coverage must cover every corpus class")
    else:
        for cls, e in cov.items():
            if e.get("declaration") not in COVERAGE:
                p.append(f"{cls}: bad coverage declaration")
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


def evaluate(inv, root: Path, orca_home: Path | None = None) -> C.CheckResult:
    """The fail-closed verdict on inventory completeness for contamination purposes."""
    name = "training_corpora_inventory"
    p = validate(inv)
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
    if inv["completeness_attestation"]["status"] != "ATTESTED_COMPLETE" or gaps:
        return C.CheckResult(name, C.INCOMPLETE, gaps, "completeness not attested (owner attestation and per-class coverage declarations required)")
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
