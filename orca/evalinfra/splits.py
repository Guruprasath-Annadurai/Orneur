"""Split-separation enforcement across SCREEN / QUALIFICATION_HOLDOUT / DEV / TRAIN.

Every ordered-unique PAIR of splits is checked (not only SCREEN vs HOLDOUT, which orca.eval.genesis_v2.isolation already covers): the TRAIN vs
QUALIFICATION_HOLDOUT pair is the one that matters most for a fine-tuning programme. Checks reuse the deterministic, local-only fingerprints of
orca.eval.genesis_v2.similarity (no model, no network):

  exact   : item id, content fingerprint (system+prompt+input+ground_truth), normalized prompt text, high-entropy hidden answer, answer leaves
  near    : word 5-gram Jaccard (>= contamination.NEAR_DUP_JACCARD), structural/skeleton clone (>= STRUCT_CLONE_JACCARD)
  cluster : a generation cluster present in two splits of the same category (template reuse) -- FAIL
  canary  : a canary string registered for split A found inside any item of split B != A -- FAIL

Findings carry opaque ids / scores / short hashes only -- never prompt or answer text. A missing split, an item without a cluster label, or a
split name outside the four is INCOMPLETE/FAIL, never silently PASS.
"""
from __future__ import annotations

import hashlib
import itertools
from dataclasses import dataclass, field

from orca.eval.genesis_v2 import contamination as C
from orca.eval.genesis_v2 import similarity as S
from orca.evalinfra.errors import SchemaViolation, SplitViolation
from orca.evalinfra.schema import SPLITS

MIN_CANARY_NORMALIZED_CHARS = 12
PASS, FAIL, INCOMPLETE = "PASS", "FAIL", "INCOMPLETE"


@dataclass
class SeparationReport:
    status: str
    findings: list = field(default_factory=list)
    checked_pairs: list = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status == PASS


def _h8(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:12]


def _validate_items(items: list) -> None:
    ids = set()
    for it in items:
        if not isinstance(it, dict) or not it.get("item_id"):
            raise SchemaViolation("BAD_ITEM", "every item needs an item_id")
        if it.get("split") not in SPLITS:
            raise SchemaViolation("BAD_SPLIT", f"{it['item_id']}: {it.get('split')!r}")
        if (it["split"], it["item_id"]) in ids:                  # the SAME id in TWO splits is a separation finding, not a schema error
            raise SchemaViolation("DUPLICATE_ITEM_ID", it["item_id"])
        ids.add((it["split"], it["item_id"]))


def _item_blob(item: dict) -> str:
    """All content fields of an item, normalized, for canary search (prompt, system, input, ground truth leaves)."""
    parts = S.string_leaves([item.get("system"), item.get("prompt"), item.get("input"), item.get("ground_truth")])
    return " " + " ".join(S.normalize(p) for p in parts) + " "


def check_canaries(items: list, canaries: dict) -> list:
    """canaries: {split: [canary_string, ...]}. Returns findings for every canary found in an item of a DIFFERENT split."""
    out = []
    for sp, lst in canaries.items():
        if sp not in SPLITS:
            raise SchemaViolation("BAD_SPLIT", f"canary registry names unknown split {sp!r}")
        for c in lst:
            n = S.normalize(c)
            if len(n) < MIN_CANARY_NORMALIZED_CHARS:
                raise SchemaViolation("CANARY_TOO_SHORT", f"a canary needs >= {MIN_CANARY_NORMALIZED_CHARS} normalized chars to avoid false matches")
    blobs = {(it["split"], it["item_id"]): _item_blob(it) for it in items}
    for sp, lst in sorted(canaries.items()):
        for c in lst:
            n = " " + S.normalize(c) + " "
            for (isp, iid), blob in sorted(blobs.items()):
                if isp != sp and n in blob:
                    out.append({"check": "canary", "canary_split": sp, "found_in_split": isp, "item": iid, "canary_sha12": _h8(S.normalize(c))})
    return out


def check_split_separation(items: list, *, canaries: dict | None = None, required_splits: tuple = SPLITS) -> SeparationReport:
    _validate_items(items)
    by = {s: [it for it in items if it["split"] == s] for s in SPLITS}
    findings: list = []
    status = PASS
    missing = [s for s in required_splits if not by.get(s)]
    if missing:
        findings.append({"check": "required_split_missing", "splits": missing})
        status = INCOMPLETE
    recs = {s: [S.make_rec(i) for i in by[s]] for s in SPLITS}
    pairs = []
    for sa, sb in itertools.combinations(SPLITS, 2):
        a, b = recs[sa], recs[sb]
        if not a or not b:
            continue
        pairs.append([sa, sb])

        def add(check, **kw):
            findings.append({"check": check, "splits": [sa, sb], **kw})

        for i in sorted({r.item_id for r in a} & {r.item_id for r in b}):
            add("exact_item_id", item=i)
        bc = {}
        for r in b:
            bc.setdefault(r.content_fp, r.item_id)
        for r in a:
            if r.content_fp in bc:
                add("exact_content_fingerprint", left=r.item_id, right=bc[r.content_fp])
        bn = {}
        for r in b:
            if r.text_norm:
                bn.setdefault(r.text_norm, r.item_id)
        for r in a:
            if r.text_norm and r.text_norm in bn:
                add("exact_prompt_text", left=r.item_id, right=bn[r.text_norm])
        bg = {}
        for r in b:
            if r.gt_canon:
                bg.setdefault(r.gt_canon, r)
        for r in a:
            if r.gt_canon in bg and C.high_entropy_answer(r):
                add("exact_hidden_answer", left=r.item_id, right=bg[r.gt_canon].item_id)
        leaf = {}
        for r in b:
            for lf in r.gt_leaves:
                leaf.setdefault(lf, r.item_id)
        for r in a:
            for lf in r.gt_leaves:
                if lf in leaf:
                    add("answer_leaf", left=r.item_id, right=leaf[lf])
                    break
        for x, y, sc in S.similar_pairs(a, b, "text", C.NEAR_DUP_JACCARD):
            add("near_duplicate_text", left=x, right=y, score=round(sc, 4))
        for x, y, sc in S.similar_pairs(a, b, "struct", C.STRUCT_CLONE_JACCARD):
            add("structural_clone", left=x, right=y, score=round(sc, 4))
        unlabeled = [r.item_id for r in a + b if not r.cluster]
        if unlabeled:
            add("cluster_label_missing", count=len(unlabeled))
        for cat in sorted({r.category for r in a} & {r.category for r in b}):
            shared = {r.cluster for r in a if r.category == cat and r.cluster} & {r.cluster for r in b if r.category == cat and r.cluster}
            for cl in sorted(shared):
                add("shared_cluster", category=cat, cluster_sha12=_h8(cl))
    if canaries:
        findings += check_canaries(items, canaries)
    if findings and status != INCOMPLETE:
        status = FAIL
    elif any(f["check"] != "required_split_missing" for f in findings):
        status = FAIL
    return SeparationReport(status, findings, pairs)


def assert_separated(items: list, **kw) -> SeparationReport:
    rep = check_split_separation(items, **kw)
    if not rep.passed:
        raise SplitViolation(rep.status, f"{len(rep.findings)} finding(s): " + ",".join(sorted({f['check'] for f in rep.findings})))
    return rep
