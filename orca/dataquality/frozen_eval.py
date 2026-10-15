"""(6) Leakage against a supplied FROZEN eval set. The eval file must match a pinned sha256 (the frozen identity) before any comparison is made;
a missing pin is NOT_EVALUATED, a mismatch is FAIL (the set is not the frozen one). Then ``contamination.check`` runs (exact, near, canary) with an
8-gram fingerprint set derived from that same frozen eval, so all comparisons use one supplied set. Output carries train-side line numbers and
counts only, never eval content.
"""
from __future__ import annotations

from orca.dataquality import FAIL, NOT_EVALUATED, PASS
from orca.dataquality import contamination as CT
from orca.dataquality._common import load_jsonl, parsed, sha256_file


def check(train_lines: list, eval_path, *, expected_sha256: str | None, canaries: list | None = None) -> dict:
    if not expected_sha256:
        return {"check": "frozen_eval", "status": NOT_EVALUATED, "reason": "no pinned eval sha256 supplied; the eval set is not shown to be frozen"}
    actual = sha256_file(eval_path)
    if actual != expected_sha256:
        return {"check": "frozen_eval", "status": FAIL, "reason": "eval_digest_mismatch", "expected_sha256": expected_sha256, "actual_sha256": actual}
    ev = load_jsonl(eval_path)
    if not parsed(ev):
        return {"check": "frozen_eval", "status": FAIL, "reason": "eval_has_no_parseable_records", "eval_sha256": actual}
    res = CT.check(train_lines, ev, canaries=canaries, fingerprint_set=CT.build_fingerprint_set(ev))
    # canaries are an optional extra here: when none are supplied the sub-check is omitted rather than left as a permanent NOT_EVALUATED
    subs = [{"name": "eval_pin", "status": PASS, "eval_sha256": actual}] + [s for s in res["sub_checks"] if canaries or s["name"] != "canary"]
    sts = [s["status"] for s in subs]
    status = FAIL if FAIL in sts else (PASS if all(s == PASS for s in sts) else NOT_EVALUATED)
    return {"check": "frozen_eval", "status": status, "eval_sha256": actual, "sub_checks": subs, "train_records": res.get("train_records"),
            "eval_records": res.get("eval_records"), "item_level_leakage": res.get("item_level_leakage")}
