"""Validator for the NON-FROZEN, NON-NORMATIVE category-mapping PROPOSAL (finding F3).

The proposal maps the 21 named V2 corpus categories (`orca.eval.genesis_eval_v1.CATEGORIES`) onto the 17 numbered capability-spec categories
(`orca.eval.genesis_suite.CATEGORY_NAMES`) so the zero-tolerance ids 10/14/15/17 can be tied to something in the V2 corpus. It is a PROPOSAL for the
founder to accept, amend or reject: nothing imports it, no preregistration, manifest, analysis plan or gate reads it, and it is deliberately shaped so
it cannot be mistaken for (or accepted as) a frozen artifact:

  * status must be PROPOSAL_NOT_FROZEN_NOT_NORMATIVE, frozen must be false, `authorizes_nothing` must be true;
  * the keys that mark frozen artifacts (`record_sha256`, `frozen_at`, `plan_sha256`, `manifest_sha256`, `signature`) are FORBIDDEN here;
  * the schema_version is `orneur-category-mapping-PROPOSAL/0` (the `PROPOSAL` token is part of the literal).
Pure data validation: no model, no network, no I/O except reading the given file.
"""
from __future__ import annotations

import json
from pathlib import Path

from orca.eval import genesis_eval_v1 as V1
from orca.eval import genesis_suite as GS

SCHEMA_VERSION = "orneur-category-mapping-PROPOSAL/0"
STATUS = "PROPOSAL_NOT_FROZEN_NOT_NORMATIVE"
RELATIONS = ("CLOSE", "PARTIAL", "WEAK", "NONE")
STRONG = ("CLOSE", "PARTIAL")                                       # relations that count as "covering" a spec category
ZERO_TOLERANCE_SPEC_IDS = (10, 14, 15, 17)
FROZEN_MARKER_KEYS = ("record_sha256", "frozen_at", "plan_sha256", "manifest_sha256", "signature", "signed_by")
TOP_KEYS = frozenset({"schema_version", "status", "frozen", "authorizes_nothing", "decision_owner", "decision_doc", "banner", "v2_to_spec",
                      "uncovered_spec_ids", "uncovered_zero_tolerance_spec_ids", "open_questions"})
ENTRY_KEYS = frozenset({"v2_category", "relation", "spec_ids", "rationale"})


def derived_uncovered(entries) -> list:
    covered = {i for e in entries if e.get("relation") in STRONG for i in e.get("spec_ids", [])}
    return sorted(set(GS.CATEGORY_NAMES) - covered)


def validate(doc) -> list:
    """Problems (empty list == structurally valid proposal). A valid proposal is still only a proposal."""
    p: list = []
    if not isinstance(doc, dict):
        return ["not an object"]
    for k in FROZEN_MARKER_KEYS:
        if k in doc:
            p.append(f"forbidden key {k!r}: a proposal must not carry frozen-artifact markers")
    if set(doc) - TOP_KEYS - set(FROZEN_MARKER_KEYS) or TOP_KEYS - set(doc):
        p.append(f"top-level keys must be exactly {sorted(TOP_KEYS)}")
    if doc.get("schema_version") != SCHEMA_VERSION:
        p.append(f"schema_version must be {SCHEMA_VERSION!r}")
    if doc.get("status") != STATUS:
        p.append(f"status must be {STATUS!r}")
    if doc.get("frozen") is not False:
        p.append("frozen must be false")
    if doc.get("authorizes_nothing") is not True:
        p.append("authorizes_nothing must be true")
    if not (isinstance(doc.get("banner"), str) and "NOT FROZEN" in doc["banner"] and "NOT NORMATIVE" in doc["banner"]):
        p.append("banner must state NOT FROZEN and NOT NORMATIVE")
    entries = doc.get("v2_to_spec")
    if not isinstance(entries, list):
        return p + ["v2_to_spec must be a list"]
    seen = []
    for e in entries:
        if not isinstance(e, dict) or set(e) != ENTRY_KEYS:
            p.append(f"entry keys must be exactly {sorted(ENTRY_KEYS)}: {e!r}")
            continue
        seen.append(e["v2_category"])
        if e["v2_category"] not in V1.CATEGORIES:
            p.append(f"unknown V2 category {e['v2_category']!r}")
        if e["relation"] not in RELATIONS:
            p.append(f"{e['v2_category']}: relation must be one of {RELATIONS}")
        ids = e["spec_ids"]
        if not (isinstance(ids, list) and all(type(i) is int and i in GS.CATEGORY_NAMES for i in ids) and len(set(ids)) == len(ids)):
            p.append(f"{e['v2_category']}: spec_ids must be distinct ids of genesis_suite.CATEGORY_NAMES")
        elif (e["relation"] == "NONE") != (ids == []):
            p.append(f"{e['v2_category']}: relation NONE <=> empty spec_ids")
        if not (isinstance(e["rationale"], str) and e["rationale"].strip()):
            p.append(f"{e['v2_category']}: rationale required")
    if sorted(seen) != sorted(V1.CATEGORIES):
        p.append("v2_to_spec must contain every V2 category exactly once")
    good = [e for e in entries if isinstance(e, dict) and set(e) == ENTRY_KEYS and isinstance(e["spec_ids"], list)]
    unc = derived_uncovered(good)
    if doc.get("uncovered_spec_ids") != unc:
        p.append(f"uncovered_spec_ids must equal the derived list {unc}")
    uz = [i for i in unc if i in ZERO_TOLERANCE_SPEC_IDS]
    if doc.get("uncovered_zero_tolerance_spec_ids") != uz:
        p.append(f"uncovered_zero_tolerance_spec_ids must equal the derived list {uz}")
    return p


def load_and_validate(path) -> tuple:
    doc = json.loads(Path(path).read_text())
    return doc, validate(doc)
