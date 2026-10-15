"""(8) Domain / category balance: counts, ratios, min-share flags.

Categories come from an explicit record field (dotted path, default tries ``category``, ``domain``, ``cluster``, ``meta.subtype``) or from an explicit
sidecar mapping {"<line>": "<category>"}. Categories are NEVER inferred from text: if no record carries a label the check is NOT_EVALUATED (the public
SFT files are bare ``{"text": ...}`` records, so for them it is).
"""
from __future__ import annotations

from orca.dataquality import FAIL, NOT_EVALUATED, PASS
from orca.dataquality._common import parsed

DEFAULT_FIELDS = ("category", "domain", "cluster", "meta.subtype")


def _get(obj: dict, path: str):
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur if isinstance(cur, str) and cur.strip() else None


def balance(lines: list, *, fields: tuple = DEFAULT_FIELDS, labels: dict | None = None, min_share: float = 0.05, min_categories: int = 2) -> dict:
    if not 0.0 <= min_share <= 1.0:
        raise ValueError("min_share must be in [0, 1]")
    recs = parsed(lines)
    cats: dict = {}
    unlabeled = 0
    for r in recs:
        c = (labels or {}).get(str(r.line))
        if c is None:
            for f in fields:
                c = _get(r.obj, f)
                if c:
                    break
        if c:
            cats[c] = cats.get(c, 0) + 1
        else:
            unlabeled += 1
    labeled = sum(cats.values())
    if labeled == 0:
        return {"check": "balance", "status": NOT_EVALUATED, "reason": f"no record carries a category label (fields tried: {list(fields)}; sidecar labels: {bool(labels)}); categories are never inferred from text",
                "records": len(recs)}
    rows = [{"category": k, "count": v, "share": round(v / labeled, 4), "below_min_share": (v / labeled) < min_share} for k, v in sorted(cats.items(), key=lambda kv: (-kv[1], kv[0]))]
    flagged = [r["category"] for r in rows if r["below_min_share"]]
    failing = []
    if flagged:
        failing.append("categories_below_min_share")
    if unlabeled:
        failing.append("unlabeled_records_present")
    if len(cats) < min_categories:
        failing.append("too_few_categories")
    top, low = rows[0]["count"], rows[-1]["count"]
    return {"check": "balance", "status": FAIL if failing else PASS, "failing_conditions": failing, "records": len(recs), "labeled": labeled, "unlabeled": unlabeled,
            "categories": rows, "flagged_below_min_share": flagged, "max_to_min_ratio": round(top / low, 3),
            "config": {"min_share": min_share, "min_categories": min_categories, "fields": list(fields)}}
