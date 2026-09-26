"""PUBLIC V2 manifest: counts, categories, difficulty/cluster distributions, opaque ids, salted commitments, aggregate hash. Never content."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter

from orca.eval.genesis_v2 import secret as sec
from orca.eval.genesis_v2 import spec

_ID = re.compile(r"^gce2-[0-9a-f]{24}$")
_HEX = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_ITEM_KEYS = frozenset({"id", "commitment"})
ALLOWED_TOP_KEYS = frozenset({"eval_version", "corpus_version", "document", "corpus_generated", "splits", "planned_counts", "aggregate_sha256",
                              "public_manifest_contains_answers", "public_manifest_contains_prompts", "note"})
ALLOWED_SPLIT_KEYS = frozenset({"item_count", "by_category", "difficulty_distribution", "cluster_counts", "items", "split_aggregate_sha256"})


class ManifestViolation(ValueError):
    pass


def _canon(o) -> str:
    return json.dumps(o, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def canonical_item(item: dict) -> str:
    return _canon(item)


def aggregate(commitments_by_split: dict) -> str:
    return hashlib.sha256(_canon({s: sorted(v) for s, v in sorted(commitments_by_split.items())}).encode()).hexdigest()


def build_public_manifest(items: list, secret: bytes) -> dict:
    """items: private in-memory records {item_id, split, category, difficulty, cluster, ...content...}. Only derived public fields are emitted."""
    splits: dict = {}
    per: dict = {s: [] for s in spec.SPLITS}
    for it in items:
        per[it["split"]].append(it)
    commits: dict = {}
    for s in spec.PRIVATE_SPLITS:
        rows = per[s]
        cs = [sec.commitment(secret, it["item_id"], canonical_item(it)) for it in rows]
        commits[s] = cs
        splits[s] = {
            "item_count": len(rows),
            "by_category": dict(sorted(Counter(it["category"] for it in rows).items())),
            "difficulty_distribution": dict(sorted(Counter(it["difficulty"] for it in rows).items())),
            "cluster_counts": {"distinct_clusters": len({it["cluster"] for it in rows}),
                               "max_cluster_size": max(Counter(it["cluster"] for it in rows).values(), default=0)},
            "items": sorted(({"id": it["item_id"], "commitment": c} for it, c in zip(rows, cs)), key=lambda r: r["id"]),
            "split_aggregate_sha256": hashlib.sha256(_canon(sorted(cs)).encode()).hexdigest()}
    m = {"eval_version": spec.EVAL_VERSION, "corpus_version": spec.CORPUS_VERSION, "document": "GENESIS_CAPABILITY_EVAL_V2_PUBLIC_MANIFEST",
         "corpus_generated": True, "splits": splits, "aggregate_sha256": aggregate(commits),
         "public_manifest_contains_answers": False, "public_manifest_contains_prompts": False}
    validate_public_manifest(m)
    return m


def validate_public_manifest(m: dict) -> None:
    """Whitelist validator: any key outside the whitelist, any content-bearing key at any depth, any non-opaque id => violation."""
    if not isinstance(m, dict) or set(m) - ALLOWED_TOP_KEYS:
        raise ManifestViolation(f"unexpected top-level keys: {sorted(set(m) - ALLOWED_TOP_KEYS) if isinstance(m, dict) else 'not a dict'}")
    _no_forbidden(m)
    if m.get("eval_version") != spec.EVAL_VERSION:
        raise ManifestViolation("wrong eval_version")
    if m.get("public_manifest_contains_answers") is not False or m.get("public_manifest_contains_prompts") is not False:
        raise ManifestViolation("manifest must state it contains no answers/prompts")
    if not m.get("corpus_generated"):
        if m.get("splits"):
            raise ManifestViolation("a manifest with no generated corpus must not list splits")
        return
    seen, commits = set(), {}
    for s, body in m["splits"].items():
        if s not in spec.PRIVATE_SPLITS:
            raise ManifestViolation(f"only private splits are committed in this manifest, got {s}")
        if set(body) - ALLOWED_SPLIT_KEYS:
            raise ManifestViolation(f"unexpected split keys {sorted(set(body) - ALLOWED_SPLIT_KEYS)}")
        if body["item_count"] != len(body["items"]) or body["item_count"] != sum(body["by_category"].values()):
            raise ManifestViolation("counts inconsistent")
        cs = []
        for r in body["items"]:
            if set(r) != ALLOWED_ITEM_KEYS or not _ID.match(r["id"]) or not _HEX.match(r["commitment"]):
                raise ManifestViolation("item rows must be exactly {opaque id, salted commitment}")
            if r["id"] in seen:
                raise ManifestViolation("item id appears twice (in one split or across SCREEN and QUALIFICATION_HOLDOUT)")
            seen.add(r["id"])
            cs.append(r["commitment"])
        if hashlib.sha256(_canon(sorted(cs)).encode()).hexdigest() != body["split_aggregate_sha256"]:
            raise ManifestViolation("split aggregate hash mismatch")
        commits[s] = cs
    if len(set(c for cs in commits.values() for c in cs)) != sum(len(c) for c in commits.values()):
        raise ManifestViolation("duplicate commitment: an item is present in more than one place")
    if aggregate(commits) != m["aggregate_sha256"]:
        raise ManifestViolation("aggregate hash mismatch")


def _no_forbidden(o, path="") -> None:
    if isinstance(o, dict):
        for k, v in o.items():
            if k in spec.FORBIDDEN_PUBLIC_KEYS:
                raise ManifestViolation(f"forbidden content-bearing key {k!r} at {path or '/'}")
            _no_forbidden(v, f"{path}/{k}")
    elif isinstance(o, list):
        for v in o:
            _no_forbidden(v, path)


def verify_commitments(m: dict, items: list, secret: bytes) -> bool:
    """Owner/qualification-runner side: prove the private corpus matches the public commitments."""
    want = {r["id"]: r["commitment"] for s in m["splits"].values() for r in s["items"]}
    got = {it["item_id"]: sec.commitment(secret, it["item_id"], canonical_item(it)) for it in items if it["split"] in spec.PRIVATE_SPLITS}
    return want == got


def check_split_separation(items: list) -> dict:
    """SCREEN and QUALIFICATION_HOLDOUT must share no item: id, exact content, or normalized-text fingerprint. Shared clusters are reported."""
    def fp(it):
        return hashlib.sha256(re.sub(r"\W+", " ", str(it.get("prompt", "")).lower()).strip().encode()).hexdigest()
    a = [i for i in items if i["split"] == "SCREEN"]
    b = [i for i in items if i["split"] == "QUALIFICATION_HOLDOUT"]
    shared_ids = {i["item_id"] for i in a} & {i["item_id"] for i in b}
    shared_fp = {fp(i) for i in a} & {fp(i) for i in b}
    shared_clusters = sorted({i["cluster"] for i in a} & {i["cluster"] for i in b})
    return {"pass": not shared_ids and not shared_fp, "shared_ids": len(shared_ids), "shared_text_fingerprints": len(shared_fp),
            "shared_clusters": shared_clusters}


def check_no_v1_reuse(items: list, v1_prompt_fingerprints: set, v1_item_ids: set) -> dict:
    def fp(it):
        return hashlib.sha256(re.sub(r"\W+", " ", str(it.get("prompt", "")).lower()).strip().encode()).hexdigest()
    reused = [i["item_id"] for i in items if fp(i) in v1_prompt_fingerprints or i["item_id"] in v1_item_ids]
    return {"pass": not reused, "reused": len(reused)}
