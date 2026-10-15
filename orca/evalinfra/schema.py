"""Evaluation schema + manifest validation (items, categories, scorers, partitions). FAIL CLOSED.

The manifest is a PUBLIC artifact: opaque ids, categories, scorer declarations, split assignment and salted commitments -- never prompts, answers,
seeds or salts. Validation is a strict whitelist at every level: an unknown field, a missing field, a duplicate id/commitment, a missing
commitment, a V1 item, an LLM-judge scorer, or a content-bearing key anywhere is a SchemaViolation. Nothing is "defaulted" or "ignored".

Splits (evalinfra naming) map onto orca.eval.genesis_v2.spec as: SCREEN=SCREEN, QUALIFICATION_HOLDOUT=QUALIFICATION_HOLDOUT, DEV=DEV, TRAIN=PILOT_TRAIN.
"""
from __future__ import annotations

import re
from collections import Counter

from orca.eval.genesis_v2 import spec as V2
from orca.evalinfra.canon import canonical, is_hex64, is_int, obj_hash, sha256_hex
from orca.evalinfra.errors import SchemaViolation

SCHEMA_VERSION = "orneur-evalinfra-manifest/1"
SPLITS = ("SCREEN", "QUALIFICATION_HOLDOUT", "DEV", "TRAIN")
PRIVATE_SPLITS = ("SCREEN", "QUALIFICATION_HOLDOUT")
V2_SPLIT_NAME = {"SCREEN": "SCREEN", "QUALIFICATION_HOLDOUT": "QUALIFICATION_HOLDOUT", "DEV": "DEV", "TRAIN": "PILOT_TRAIN"}
SCORER_TYPES = ("exact_match", "keyword", "pattern_match", "schema_match", "unit_test", "structured_fixture", "human_rubric")
FORBIDDEN_SCORER_TYPES = ("llm_judge", "model_judge", "llm", "model")        # no model-as-judge anywhere in this package
ROLES = ("GATING", "REPORT_ONLY")

TOP_KEYS = frozenset({"schema_version", "eval_id", "eval_version", "synthetic", "taxonomy", "categories", "scorers", "partitions", "items", "manifest_sha256"})
CATEGORY_KEYS = frozenset({"id", "name", "scorer", "role", "zero_tolerance"})
SCORER_KEYS = frozenset({"id", "type", "version"})
PARTITION_KEYS = frozenset({"split", "item_count", "by_category", "partition_sha256"})
ITEM_KEYS = frozenset({"id", "category", "split", "scorer", "commitment"})

_ITEM_ID = re.compile(r"^(gce2|syn)-[0-9a-f]{12,64}$")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/ -]{0,95}$")


def _fail(code: str, detail: str = ""):
    raise SchemaViolation(code, detail)


def _exact(obj, keys, where: str) -> None:
    if not isinstance(obj, dict):
        _fail("NOT_AN_OBJECT", where)
    extra, missing = set(obj) - keys, keys - set(obj)
    if extra:
        _fail("UNKNOWN_FIELD", f"{where}: {sorted(map(str, extra))}")
    if missing:
        _fail("MISSING_FIELD", f"{where}: {sorted(missing)}")


def _scan_forbidden(o, path: str = "") -> None:
    if isinstance(o, dict):
        for k, v in o.items():
            if k in V2.FORBIDDEN_PUBLIC_KEYS:
                _fail("CONTENT_BEARING_KEY", f"{k!r} at {path or '/'}")
            _scan_forbidden(v, f"{path}/{k}")
    elif isinstance(o, list):
        for v in o:
            _scan_forbidden(v, path)


def partition_hash(split: str, commitments: list) -> str:
    return obj_hash({"split": split, "commitments": sorted(map(str, commitments))})


def manifest_hash(m: dict) -> str:
    return obj_hash({k: v for k, v in m.items() if k != "manifest_sha256"})


def validate_manifest(m) -> dict:
    """Returns the manifest if (and only if) it is fully valid; raises SchemaViolation otherwise."""
    _exact(m, TOP_KEYS, "manifest")
    _scan_forbidden(m)
    if m["schema_version"] != SCHEMA_VERSION:
        _fail("SCHEMA_VERSION_MISMATCH", str(m["schema_version"]))
    if not isinstance(m["synthetic"], bool):
        _fail("TYPE_ERROR", "synthetic must be a bool")
    if not (isinstance(m["eval_id"], str) and _NAME.match(m["eval_id"])):
        _fail("BAD_EVAL_ID")
    ev = m["eval_version"]
    if not isinstance(ev, str) or not ev:
        _fail("BAD_EVAL_VERSION")
    if ev.startswith("genesis-capability-eval/1"):
        _fail("V1_REFUSED", "V1 is permanently invalid as private evidence")
    if m["synthetic"]:
        if not ev.startswith("SYNTHETIC"):
            _fail("SYNTHETIC_VERSION_LABEL", "a synthetic manifest's eval_version must start with SYNTHETIC")
    elif ev != V2.EVAL_VERSION:
        _fail("WRONG_EVAL_VERSION", ev)
    if not (isinstance(m["taxonomy"], str) and _NAME.match(m["taxonomy"])):
        _fail("BAD_TAXONOMY")

    # scorers
    if not isinstance(m["scorers"], list) or not m["scorers"]:
        _fail("NO_SCORERS")
    scorers = {}
    for s in m["scorers"]:
        _exact(s, SCORER_KEYS, "scorer")
        if not (isinstance(s["id"], str) and _NAME.match(s["id"])) or not (isinstance(s["version"], str) and s["version"]):
            _fail("BAD_SCORER", str(s.get("id")))
        if s["type"] in FORBIDDEN_SCORER_TYPES:
            _fail("LLM_JUDGE_FORBIDDEN", s["id"])
        if s["type"] not in SCORER_TYPES:
            _fail("UNKNOWN_SCORER_TYPE", str(s["type"]))
        if s["id"] in scorers:
            _fail("DUPLICATE_SCORER", s["id"])
        scorers[s["id"]] = s

    # categories
    if not isinstance(m["categories"], list) or not m["categories"]:
        _fail("NO_CATEGORIES")
    cats = {}
    for c in m["categories"]:
        _exact(c, CATEGORY_KEYS, "category")
        cid = c["id"]
        if not (is_int(cid) or (isinstance(cid, str) and _NAME.match(cid))):
            _fail("BAD_CATEGORY_ID", repr(cid))
        if cid in cats:
            _fail("DUPLICATE_CATEGORY", repr(cid))
        if not (isinstance(c["name"], str) and _NAME.match(c["name"])):
            _fail("BAD_CATEGORY_NAME", repr(cid))
        if c["scorer"] not in scorers:
            _fail("UNKNOWN_SCORER", f"category {cid!r} -> {c['scorer']!r}")
        if c["role"] not in ROLES:
            _fail("BAD_ROLE", repr(cid))
        if not isinstance(c["zero_tolerance"], bool):
            _fail("TYPE_ERROR", f"zero_tolerance of {cid!r}")
        cats[cid] = c

    # items
    if not isinstance(m["items"], list) or not m["items"]:
        _fail("NO_ITEMS")
    ids, commits, per_split = set(), {}, {s: [] for s in SPLITS}
    for it in m["items"]:
        _exact(it, ITEM_KEYS, "item")
        iid = it["id"]
        if not (isinstance(iid, str) and _ITEM_ID.match(iid)):
            _fail("BAD_ITEM_ID", "ids must be opaque gce2-<hex>/syn-<hex>" + (" (V1 ids are refused)" if str(iid).startswith("gce1-") else ""))
        if iid in ids:
            _fail("DUPLICATE_ITEM_ID", iid)
        ids.add(iid)
        if it["split"] not in SPLITS:
            _fail("BAD_SPLIT", str(it["split"]))
        if isinstance(it["category"], bool) or not isinstance(it["category"], (int, str)) or it["category"] not in cats:
            _fail("UNKNOWN_CATEGORY", f"{iid}: {it['category']!r}")
        if it["scorer"] != cats[it["category"]]["scorer"]:
            _fail("SCORER_CATEGORY_MISMATCH", iid)
        if not is_hex64(it["commitment"]):
            _fail("MISSING_OR_BAD_COMMITMENT", iid)
        if it["commitment"] in commits:
            _fail("DUPLICATE_COMMITMENT", f"{iid} and {commits[it['commitment']]} (an item is present in more than one place)")
        commits[it["commitment"]] = iid
        per_split[it["split"]].append(it)

    # partitions
    if not isinstance(m["partitions"], list):
        _fail("BAD_PARTITIONS")
    seen_parts = set()
    for p in m["partitions"]:
        _exact(p, PARTITION_KEYS, "partition")
        sp = p["split"]
        if sp not in SPLITS or sp in seen_parts:
            _fail("BAD_OR_DUPLICATE_PARTITION", str(sp))
        seen_parts.add(sp)
        rows = per_split[sp]
        if not is_int(p["item_count"]) or p["item_count"] != len(rows):
            _fail("PARTITION_COUNT_MISMATCH", sp)
        if p["by_category"] != dict(sorted(Counter(str(r["category"]) for r in rows).items())):
            _fail("PARTITION_CATEGORY_MISMATCH", sp)
        if p["partition_sha256"] != partition_hash(sp, [r["commitment"] for r in rows]):
            _fail("PARTITION_HASH_MISMATCH", sp)
    if seen_parts != {s for s in SPLITS if per_split[s]}:
        _fail("PARTITIONS_DO_NOT_COVER_ITEMS")
    if m["manifest_sha256"] != manifest_hash(m):
        _fail("MANIFEST_HASH_MISMATCH")
    return m


def build_manifest(*, eval_id: str, eval_version: str, synthetic: bool, taxonomy: str, categories: list, scorers: list, items: list) -> dict:
    """Assembles a manifest (computing partitions + hash) and validates it. Items need exactly {id, category, split, scorer, commitment}."""
    per = {s: [] for s in SPLITS}
    for it in items:
        if isinstance(it, dict) and isinstance(it.get("split"), str) and it.get("split") in per:
            per[it["split"]].append(it)
    parts = [{"split": s, "item_count": len(r), "by_category": dict(sorted(Counter(str(x.get("category")) for x in r).items())),
              "partition_sha256": partition_hash(s, [x.get("commitment") for x in r])} for s, r in per.items() if r]
    m = {"schema_version": SCHEMA_VERSION, "eval_id": eval_id, "eval_version": eval_version, "synthetic": synthetic, "taxonomy": taxonomy,
         "categories": categories, "scorers": scorers, "partitions": parts, "items": sorted(items, key=lambda r: str(r.get("id"))), "manifest_sha256": ""}
    m["manifest_sha256"] = manifest_hash(m)
    return validate_manifest(m)


def synthetic_commitment(salt_label: str, item_id: str, content: dict) -> str:
    """SYNTHETIC-fixture commitment: sha256(domain|salt-label|id|canonical content). The salt is a public label (nothing secret); real commitments use
    orca.eval.genesis_v2.secret.commitment with a custody-held secret and are never computed in this package."""
    return sha256_hex(b"evalinfra/synthetic-commitment\x1f" + salt_label.encode() + b"\x1f" + item_id.encode() + b"\x1f" + canonical(content).encode())
