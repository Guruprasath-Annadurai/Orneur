"""SCREEN vs QUALIFICATION_HOLDOUT isolation policy. Any violation FAILS; nothing is merely 'reported'.

The category table below is the explicit separation policy. `shared_cluster_policy` is FAIL for every category: procedural generators make
generation clusters the unit of template reuse, so a cluster present in both splits is a template shared between Stage-1 and the final
qualification. A category could only be relaxed by supplying a written `independence_justification` (>= 40 chars) — none currently is.
"""
from __future__ import annotations

from orca.eval.genesis_v2 import contamination as C
from orca.eval.genesis_v2 import similarity as S
from orca.eval.genesis_v2 import spec
from orca.eval.genesis_v2.contamination import CheckResult
from orca.eval.genesis_v2.spec import CATEGORIES, CATEGORY_SPECS

# structural: RELIABLE = prompts long/varied enough for skeleton fingerprints; LIMITED = short prompts, images or long-document filler: skeleton
# similarity is not trustworthy, private manual/semantic review is REQUIRED before freeze.
# answer_overlap: HIGH_ENTROPY_ONLY = exact hidden-answer equality is meaningful only for high-entropy answers (low-entropy answers such as a single
# name/number/label collide innocently and are covered by the surface/structural checks instead).
_LIMITED = {"reasoning", "mathematics", "multilingual", "verification", "long_context", "multimodal_where_applicable", "strict_contracts"}
SEPARATION_POLICY: dict = {}
for _c in CATEGORIES:
    if CATEGORY_SPECS[_c]["role"] == "PROTOCOL":
        SEPARATION_POLICY[_c] = {"applicable": False, "reason": "protocol category: no question items"}
        continue
    SEPARATION_POLICY[_c] = {
        "applicable": True,
        "risk": "HIGH",
        "shared_cluster_policy": "FAIL",
        "independence_justification": None,
        "structural_fingerprint": "LIMITED_MANUAL_REVIEW_REQUIRED" if _c in _LIMITED else "RELIABLE",
        "answer_overlap": "HIGH_ENTROPY_ONLY",
        "near_duplicate": "FAIL",
    }


def policy_problems() -> list:
    out = []
    for c, p in SEPARATION_POLICY.items():
        if not p.get("applicable"):
            continue
        if p["shared_cluster_policy"] != "FAIL" and len(p.get("independence_justification") or "") < 40:
            out.append(f"{c}: shared clusters allowed without a documented independence justification")
    if set(SEPARATION_POLICY) != set(CATEGORIES):
        out.append("policy table does not cover every category")
    return out


def check_split_isolation(items: list) -> list:
    scr = [i for i in items if i.get("split") == "SCREEN"]
    hold = [i for i in items if i.get("split") == "QUALIFICATION_HOLDOUT"]
    if not scr or not hold:
        return [CheckResult("split_isolation", C.INCOMPLETE, [], "both SCREEN and QUALIFICATION_HOLDOUT items are required")]
    a, b = [S.make_rec(i) for i in scr], [S.make_rec(i) for i in hold]
    res = []
    ids = sorted({r.item_id for r in a} & {r.item_id for r in b})
    res.append(CheckResult("isolation_item_id", C.FAIL if ids else C.PASS, [{"item": i} for i in ids]))
    bc = {}
    for r in b:
        bc.setdefault(r.content_fp, []).append(r.item_id)
    comm = [{"screen": r.item_id, "holdout": bc[r.content_fp][0]} for r in a if r.content_fp in bc]
    res.append(CheckResult("isolation_content_commitment", C.FAIL if comm else C.PASS, comm))
    bn = {}
    for r in b:
        bn.setdefault(r.text_norm, []).append(r.item_id)
    txt = [{"screen": r.item_id, "holdout": bn[r.text_norm][0]} for r in a if r.text_norm and r.text_norm in bn]
    res.append(CheckResult("isolation_text_fingerprint", C.FAIL if txt else C.PASS, txt))
    bg = {}
    for r in b:
        if r.gt_canon:
            bg.setdefault(r.gt_canon, []).append(r)
    ans = []
    for r in a:
        if not r.gt_canon or r.gt_canon not in bg:
            continue
        pol = SEPARATION_POLICY.get(r.category, {})
        if pol.get("applicable") and pol["answer_overlap"] == "HIGH_ENTROPY_ONLY" and not C.high_entropy_answer(r):
            continue
        ans.append({"screen": r.item_id, "holdout": bg[r.gt_canon][0].item_id})
    leaf = {}
    for r in b:
        for lf in r.gt_leaves:
            leaf.setdefault(lf, r.item_id)
    for r in a:
        for lf in r.gt_leaves:
            if lf in leaf:
                ans.append({"screen": r.item_id, "holdout": leaf[lf], "kind": "REFERENCE_LEAF"})
                break
    res.append(CheckResult("isolation_hidden_answer", C.FAIL if ans else C.PASS, ans))
    near = [{"screen": x, "holdout": y, "score": s} for x, y, s in S.similar_pairs(a, b, "text", C.NEAR_DUP_JACCARD)]
    res.append(CheckResult("isolation_near_duplicate", C.FAIL if near else C.PASS, near, f"Jaccard >= {C.NEAR_DUP_JACCARD}"))
    struct = [{"screen": x, "holdout": y, "score": s} for x, y, s in S.similar_pairs(a, b, "struct", C.STRUCT_CLONE_JACCARD)]
    res.append(CheckResult("isolation_structural_clone", C.FAIL if struct else C.PASS, struct, f"skeleton Jaccard >= {C.STRUCT_CLONE_JACCARD}"))
    shared = []
    for cat in sorted({r.category for r in a}):
        pol = SEPARATION_POLICY.get(cat)
        if pol is None or not pol.get("applicable"):
            shared.append({"category": cat, "problem": "no separation policy for category"})
            continue
        if pol["shared_cluster_policy"] == "FAIL":
            ca = {r.cluster for r in a if r.category == cat and r.cluster}
            cb = {r.cluster for r in b if r.category == cat and r.cluster}
            shared += [{"category": cat, "cluster_hash": S._h64(cl)} for cl in sorted(ca & cb)]
    missing_cluster = [r.item_id for r in a + b if not r.cluster]
    if missing_cluster:
        shared.append({"problem": "items without a cluster label", "count": len(missing_cluster)})
    res.append(CheckResult("isolation_shared_cluster", C.FAIL if shared else C.PASS, shared, "category separation policy: shared clusters FAIL"))
    limited = sorted({r.category for r in a + b if SEPARATION_POLICY.get(r.category, {}).get("structural_fingerprint") != "RELIABLE"})
    res.append(CheckResult("isolation_structure_review", C.PASS if not limited else C.INCOMPLETE, [{"category": c} for c in limited],
                           "categories whose structural fingerprint is limited require private manual/semantic review before freeze"))
    return res


def screen_holdout_separation_pass(results: list) -> bool:
    by = {r.name: r.status for r in results}
    need = ("isolation_item_id", "isolation_content_commitment", "isolation_text_fingerprint", "isolation_hidden_answer",
            "isolation_near_duplicate", "isolation_structural_clone", "isolation_shared_cluster", "isolation_structure_review")
    return all(by.get(n) == C.PASS for n in need) and not policy_problems()
