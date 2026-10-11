"""(6) Train/eval contamination checks: exact, near, canary-string and fingerprint-set. Deterministic, CPU only, no network.

NO ITEM-LEVEL LEAKAGE IN OUTPUT: the report contains counts, maxima, digests-prefixes of canary ids, and ONLY the *train-side* 1-based line numbers of
offending records (so the contamination can be removed from the training file). It never contains eval content, eval ids/line numbers, or scores
attributable to a specific eval item.

Roll-up rule (never optimistic): the contamination check is PASS only if all four sub-checks are PASS; any FAIL => FAIL; otherwise (some sub-checks
could not run because their input was not supplied) => NOT_EVALUATED. Thresholds are reused from orca.eval.genesis_v2.contamination / genesis_contamination.
"""
from __future__ import annotations

import itertools

from orca.dataquality import FAIL, NOT_EVALUATED, PASS
from orca.dataquality._common import body_text, mask_numbers, normalize, parsed, sha256_text, string_leaves, tokens
from orca.eval.genesis_contamination import TRAIN_NGRAM, TRAIN_OVERLAP_THRESHOLD, ngram_overlap, word_ngrams
from orca.eval.genesis_v2 import contamination as C
from orca.eval.genesis_v2 import similarity as S

FINGERPRINT_SCHEMA = "orneur-fingerprint-set/1"
ALL_PAIRS_BUDGET = 5_000_000


def build_fingerprint_set(eval_lines: list) -> dict:
    """Fingerprint (hashed word 8-grams, genesis_contamination scheme) of the eval bodies; carries no recoverable text."""
    hashes: set = set()
    for r in parsed(eval_lines):
        hashes |= word_ngrams(body_text(r.obj), TRAIN_NGRAM)
    return {"schema": FINGERPRINT_SCHEMA, "ngram": TRAIN_NGRAM, "hashes": sorted(hashes)}


def _sub(name: str, status: str, **kw) -> dict:
    return {"name": name, "status": status, **kw}


def _cap(lines: list) -> list:
    return sorted(set(lines))[:500]


def check(train_lines: list, eval_lines: list | None, *, canaries: list | None = None, fingerprint_set: dict | None = None,
          near_threshold: float = C.NEAR_DUP_JACCARD, shingle_n: int = S.SHINGLE_N, fingerprint_threshold: float = TRAIN_OVERLAP_THRESHOLD) -> dict:
    train = parsed(train_lines)
    subs = []
    ev = parsed(eval_lines) if eval_lines is not None else None
    if not ev:
        why = "no eval split supplied" if eval_lines is None else "eval split has no parseable records"
        subs += [_sub("exact", NOT_EVALUATED, reason=why), _sub("near", NOT_EVALUATED, reason=why)]
    else:
        t_norm = [normalize(body_text(r.obj)) for r in train]
        e_norm = [normalize(body_text(r.obj)) for r in ev]
        e_set = set(e_norm)
        exact_hits = [train[i].line for i, x in enumerate(t_norm) if x in e_set]
        e_masked = {mask_numbers(x) for x in e_norm}
        numeric_hits = [train[i].line for i, x in enumerate(t_norm) if x not in e_set and mask_numbers(x) in e_masked and x.strip()]
        subs.append(_sub("exact", FAIL if (exact_hits or numeric_hits) else PASS, train_records_matching_eval_exactly=len(exact_hits),
                         train_records_matching_eval_up_to_number_changes=len(numeric_hits), train_lines=_cap(exact_hits + numeric_hits),
                         comparison="normalised body (NFKC, casefold, homoglyph fold, punctuation/whitespace collapse); digits masked for the number-variant count"))
        t_sh = [S.shingle_set(tokens(body_text(r.obj)), shingle_n) for r in train]
        e_sh = [S.shingle_set(tokens(body_text(r.obj)), shingle_n) for r in ev]
        near_train: set = set()
        eval_hit = set()
        mx = 0.0
        if len(t_sh) * len(e_sh) <= ALL_PAIRS_BUDGET:
            for i, j in itertools.product(range(len(t_sh)), range(len(e_sh))):
                if t_sh[i] or e_sh[j]:
                    s = S.jaccard(t_sh[i], e_sh[j])
                    mx = max(mx, s)
                    if s >= near_threshold:
                        near_train.add(train[i].line)
                        eval_hit.add(j)
            method = "all_pairs_exact_jaccard"
        else:
            buckets: dict = {}
            for j, sh in enumerate(e_sh):
                for band in S.bands(S.minhash(sh)):
                    buckets.setdefault(band, []).append(j)
            for i, sh in enumerate(t_sh):
                cand = {j for band in S.bands(S.minhash(sh)) for j in buckets.get(band, ())}
                for j in sorted(cand):
                    s = S.jaccard(sh, e_sh[j])
                    mx = max(mx, s)
                    if s >= near_threshold:
                        near_train.add(train[i].line)
                        eval_hit.add(j)
            method = "minhash_lsh_candidates_exact_verified"
        subs.append(_sub("near", FAIL if near_train else PASS, train_records_near_eval=len(near_train), eval_items_affected_count=len(eval_hit),
                         max_jaccard_observed=round(mx, 4), threshold=near_threshold, shingle_n=shingle_n, method=method, train_lines=_cap(list(near_train))))
    if not canaries:
        subs.append(_sub("canary", NOT_EVALUATED, reason="no canary strings supplied"))
    else:
        joined = [(r.line, normalize(" ".join(string_leaves(r.obj))), "\n".join(string_leaves(r.obj))) for r in train]
        hits: dict = {}
        for c in canaries:
            nc = normalize(c)
            if len(nc) < 8:
                return {"check": "contamination", "status": FAIL, "reason": "canary too short to be unique (<8 normalised chars)", "sub_checks": subs}
            lines_hit = [ln for ln, nt, raw in joined if nc in nt or c in raw]
            if lines_hit:
                hits[sha256_text(c)[:12]] = lines_hit
        subs.append(_sub("canary", FAIL if hits else PASS, canaries_checked=len(canaries), canaries_found_in_train=len(hits), canary_id_prefixes=sorted(hits),
                         train_lines=_cap([ln for v in hits.values() for ln in v])))
    if not fingerprint_set:
        subs.append(_sub("fingerprint_set", NOT_EVALUATED, reason="no eval fingerprint set supplied"))
    elif fingerprint_set.get("schema") != FINGERPRINT_SCHEMA or fingerprint_set.get("ngram") != TRAIN_NGRAM or not isinstance(fingerprint_set.get("hashes"), list):
        subs.append(_sub("fingerprint_set", FAIL, reason=f"fingerprint set malformed or wrong scheme (need schema {FINGERPRINT_SCHEMA}, ngram {TRAIN_NGRAM})"))
    else:
        fp = set(fingerprint_set["hashes"])
        flagged, mo = [], 0.0
        for r in train:
            o = ngram_overlap(body_text(r.obj), fp, TRAIN_NGRAM)
            mo = max(mo, o)
            if o >= fingerprint_threshold:
                flagged.append(r.line)
        subs.append(_sub("fingerprint_set", FAIL if flagged else PASS, train_records_over_overlap_threshold=len(flagged), max_overlap_fraction=round(mo, 4),
                         threshold=fingerprint_threshold, ngram=TRAIN_NGRAM, fingerprint_set_size=len(fp), train_lines=_cap(flagged)))
    sts = [s["status"] for s in subs]
    status = FAIL if FAIL in sts else (PASS if all(s == PASS for s in sts) else NOT_EVALUATED)
    return {"check": "contamination", "status": status, "train_records": len(train), "eval_records": len(ev) if ev is not None else None,
            "sub_checks": subs, "item_level_leakage": "none: only train-side line numbers, counts and canary-id prefixes are emitted"}
