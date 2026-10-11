"""(4) Exact- and near-duplicate detection, cluster statistics and template-concentration metrics. Deterministic; CPU only.

What is compared: ``body_text`` of each record = the content turns with the (shared) system-prompt block and chat-template control tokens removed,
so identical boilerplate cannot inflate similarity.

Signals
  * exact_raw        : identical body bytes.
  * exact_normalized : identical after NFKC + casefold + zero-width removal + homoglyph folding + punctuation/whitespace collapse.
  * numeric_variant  : identical after normalisation AND digit-runs masked to '#', but not exact_normalized (same record, changed numbers).
  * near-duplicate   : exact Jaccard of word k-shingles >= threshold (default k=3, 0.80). For n <= ALL_PAIRS_MAX every pair is evaluated; above that,
                       MinHash/LSH candidate generation (orca.eval.genesis_v2.similarity, 64 perms, 32x2 bands) followed by EXACT Jaccard verification.
  * template concentration: records mapped to a skeleton (function words kept, other tokens -> 'w'/'#') over the full body and over the opening 8 tokens;
                       reported as distinct count, top shares and normalised Shannon entropy.

The separate ``legacy_quick_ratio`` function reproduces the character-multiset figure documented in docs/orneur/phase-0/GENESIS_DATASET_BASELINE.md.
"""
from __future__ import annotations

import difflib
import itertools
import math
from collections import Counter

from orca.dataquality import FAIL, NOT_EVALUATED, PASS
from orca.dataquality._common import body_text, legacy_body_text, mask_numbers, normalize, parsed, sha256_text, tokens
from orca.eval.genesis_v2 import contamination as C
from orca.eval.genesis_v2 import similarity as S

ALL_PAIRS_MAX = 3000
DEFAULT_SHINGLE_N = 3
DEFAULT_THRESHOLD = 0.80
DEFAULT_MAX_NEAR_RECORD_FRACTION = 0.10
LEGACY_THRESHOLD = 0.85
LEGACY_MAX_RECORDS = 400
OPENING_TOKENS = 8


class _UF:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)   # smallest index is the root => deterministic


def _groups(keys: list, lines: list, limit: int = 100) -> tuple:
    by: dict = {}
    for i, k in enumerate(keys):
        by.setdefault(k, []).append(i)
    dup = [v for v in by.values() if len(v) > 1]
    dup.sort(key=lambda v: v[0])
    redundant = sum(len(v) - 1 for v in dup)
    listed = [[lines[i].line for i in v] for v in dup[:limit]]
    return len(dup), redundant, listed


def _entropy(counter: Counter) -> tuple:
    n = sum(counter.values())
    if n == 0:
        return 0.0, 0.0
    h = -sum((c / n) * math.log2(c / n) for c in counter.values())
    hmax = math.log2(len(counter)) if len(counter) > 1 else 0.0
    return h, (h / hmax if hmax else 0.0)


def _top(counter: Counter, n_total: int, k: int = 5) -> list:
    items = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
    return [{"template_sha256_prefix": sha256_text(key)[:12], "count": c, "share": round(c / n_total, 4)} for key, c in items]


def near_pairs(shingles: list, sigs: list, threshold: float) -> tuple:
    """Return ([(i, j, jaccard)], method)."""
    n = len(shingles)
    out = []
    if n <= ALL_PAIRS_MAX:
        for i, j in itertools.combinations(range(n), 2):
            if not shingles[i] and not shingles[j]:
                continue
            s = S.jaccard(shingles[i], shingles[j])
            if s >= threshold:
                out.append((i, j, round(s, 4)))
        return out, "all_pairs_exact_jaccard"
    buckets: dict = {}
    for i, sg in enumerate(sigs):
        if sg:
            for band in S.bands(sg):
                buckets.setdefault(band, []).append(i)
    seen = set()
    for members in buckets.values():
        for a, b in itertools.combinations(members, 2):
            if (a, b) in seen:
                continue
            seen.add((a, b))
            s = S.jaccard(shingles[a], shingles[b])
            if s >= threshold:
                out.append((a, b, round(s, 4)))
    return sorted(out), "minhash_lsh_candidates_exact_verified"


def _structural_clones(toks: list, recs: list, threshold: float = C.STRUCT_CLONE_JACCARD) -> dict:
    """Pairs whose SKELETON (function words kept, other tokens -> 'w'/'#') word-4-gram Jaccard >= threshold: same template, different names/numbers/words.
    Reuses genesis_v2 similarity primitives and its STRUCT_CLONE_JACCARD constant. Descriptive; not a FAIL condition by default."""
    n = len(toks)
    if n > ALL_PAIRS_MAX:
        return {"status": NOT_EVALUATED, "reason": f"more than {ALL_PAIRS_MAX} records; structural all-pairs not run"}
    skel = [S.shingle_set(S.skeleton_tokens(t), S.SKEL_N) if len(t) >= S.MIN_TOKENS_STRUCT else frozenset() for t in toks]
    pairs, involved = 0, set()
    for i, j in itertools.combinations(range(n), 2):
        if skel[i] and skel[j] and S.jaccard(skel[i], skel[j]) >= threshold:
            pairs += 1
            involved.update((i, j))
    total = n * (n - 1) // 2
    return {"status": "MEASURED", "threshold": threshold, "min_tokens": S.MIN_TOKENS_STRUCT, "pairs": pairs, "pair_fraction": round(pairs / total, 4) if total else 0.0,
            "records_involved": len(involved), "record_fraction": round(len(involved) / n, 4), "records_too_short_to_assess": sum(1 for s in skel if not s),
            "lines_involved": [recs[i].line for i in sorted(involved)][:200]}


def analyze(lines: list, *, threshold: float = DEFAULT_THRESHOLD, shingle_n: int = DEFAULT_SHINGLE_N,
            max_near_record_fraction: float = DEFAULT_MAX_NEAR_RECORD_FRACTION, max_exact_groups: int = 0) -> dict:
    if not 0.0 < threshold <= 1.0:
        raise ValueError("threshold must be in (0, 1]")
    recs = parsed(lines)
    n = len(recs)
    if n < 2:
        return {"check": "dedup", "status": NOT_EVALUATED, "reason": "fewer than 2 parseable records", "records": n}
    bodies = [body_text(r.obj) for r in recs]
    toks = [tokens(b) for b in bodies]
    norms = [" ".join(t) for t in toks]
    raw_n, raw_red, raw_list = _groups(bodies, recs)
    norm_n, norm_red, norm_list = _groups(norms, recs)
    masked = [mask_numbers(x) for x in norms]
    mask_n, mask_red, mask_list = _groups(masked, recs)
    # numeric variants = masked groups that are NOT already exact-normalized duplicates
    by_mask: dict = {}
    for i, m in enumerate(masked):
        by_mask.setdefault(m, set()).add(norms[i])
    numeric_variant_groups = sorted([sorted(i for i, m in enumerate(masked) if m == key) for key, forms in by_mask.items() if len(forms) > 1 and key.strip()], key=lambda v: v[0])
    numeric_variant_records = sum(len(g) for g in numeric_variant_groups)

    shingles = [S.shingle_set(t, shingle_n) if t else frozenset() for t in toks]
    sigs = [S.minhash(s) for s in shingles] if n > ALL_PAIRS_MAX else [()] * n
    pairs, method = near_pairs(shingles, sigs, threshold)
    uf = _UF(n)
    for i, j, _ in pairs:
        uf.union(i, j)
    comp: dict = {}
    for i in range(n):
        comp.setdefault(uf.find(i), []).append(i)
    clusters = sorted((v for v in comp.values() if len(v) > 1), key=lambda v: v[0])
    in_cluster = sum(len(c) for c in clusters)
    redundant = n - len(comp)
    total_pairs = n * (n - 1) // 2

    struct = _structural_clones(toks, recs)
    skel_full = Counter(" ".join(S.skeleton_tokens(t)) for t in toks)
    skel_open = Counter(" ".join(S.skeleton_tokens(t[:OPENING_TOKENS])) for t in toks)
    hf, hf_norm = _entropy(skel_full)
    ho, ho_norm = _entropy(skel_open)
    near_fraction = in_cluster / n
    failing = []
    if norm_n > max_exact_groups:
        failing.append("exact_normalized_duplicates_exceed_limit")
    if near_fraction > max_near_record_fraction:
        failing.append("near_duplicate_record_fraction_exceeds_limit")
    return {
        "check": "dedup", "status": PASS if not failing else FAIL, "failing_conditions": failing,
        "records": n, "unparseable_lines_excluded": len(lines) - n,
        "config": {"shingle_n": shingle_n, "jaccard_threshold": threshold, "near_method": method, "max_near_record_fraction": max_near_record_fraction,
                   "max_exact_normalized_groups": max_exact_groups, "compared_text": "body_text (system block and template control tokens excluded)"},
        "exact_raw": {"duplicate_groups": raw_n, "redundant_records": raw_red, "groups_by_line": raw_list},
        "exact_normalized": {"duplicate_groups": norm_n, "redundant_records": norm_red, "groups_by_line": norm_list},
        "numeric_variants": {"groups": len(numeric_variant_groups), "records": numeric_variant_records,
                             "groups_by_line": [[recs[i].line for i in g] for g in numeric_variant_groups[:100]]},
        "near_duplicates": {
            "pairs_total": total_pairs, "pairs_at_or_above_threshold": len(pairs),
            "pair_fraction": round(len(pairs) / total_pairs, 6) if total_pairs else 0.0,
            "clusters": len(clusters), "records_in_clusters": in_cluster, "record_fraction_in_clusters": round(near_fraction, 4),
            "largest_cluster_size": max((len(c) for c in clusters), default=1), "redundant_records_if_one_kept_per_cluster": redundant,
            "unique_records_after_dedup": n - redundant,
            "cluster_size_histogram": dict(sorted(Counter(len(c) for c in clusters).items())),
            "clusters_by_line": [[recs[i].line for i in c] for c in clusters[:100]],
            "max_pair_score": max((p[2] for p in pairs), default=0.0),
        },
        "structural_clones": struct,
        "template_concentration": {
            "full_skeleton": {"distinct": len(skel_full), "top": _top(skel_full, n), "top1_share": round(max(skel_full.values()) / n, 4),
                              "entropy_bits": round(hf, 4), "normalized_entropy": round(hf_norm, 4)},
            "opening_skeleton": {"tokens": OPENING_TOKENS, "distinct": len(skel_open), "top": _top(skel_open, n), "top1_share": round(max(skel_open.values()) / n, 4),
                                 "entropy_bits": round(ho, 4), "normalized_entropy": round(ho_norm, 4)},
        },
    }


def legacy_quick_ratio(lines_groups: dict, *, threshold: float = LEGACY_THRESHOLD) -> dict:
    """Reproduce the documented ``difflib.SequenceMatcher.quick_ratio() > 0.85`` measurement.

    ``lines_groups``: {label: [Line...]} -- records of every group are pooled into one pair universe (the documented 666 = C(37,2) pools nano train 34 +
    eval 3). Text compared = everything after the first ``<|eot_id|>`` (system block excluded). IMPORTANT: quick_ratio is an UPPER BOUND that only
    compares character multisets (order-blind); the order-aware ``ratio()`` is reported alongside so the two are never confused.
    """
    recs = [r for g in lines_groups.values() for r in parsed(g)]
    texts = [legacy_body_text(r.obj) for r in recs]
    n = len(texts)
    if n < 2 or n > LEGACY_MAX_RECORDS:
        return {"status": NOT_EVALUATED, "reason": f"needs 2..{LEGACY_MAX_RECORDS} records, got {n}"}
    q = r_ = 0
    for a, b in itertools.combinations(texts, 2):
        sm = difflib.SequenceMatcher(None, a, b)
        q += sm.quick_ratio() > threshold
        r_ += sm.ratio() > threshold
    total = n * (n - 1) // 2
    return {
        "status": "MEASURED", "records_pooled": n, "pools": {k: len(parsed(v)) for k, v in sorted(lines_groups.items())}, "pairs_total": total,
        "threshold_strictly_greater_than": threshold, "text_compared": "everything after the first <|eot_id|> (system-prompt block excluded)",
        "quick_ratio_pairs_over_threshold": q, "quick_ratio_fraction": round(q / total, 4),
        "ratio_pairs_over_threshold": r_, "ratio_fraction": round(r_ / total, 4),
        "caveat": "quick_ratio is a character-multiset upper bound, not edit similarity; ratio() is the order-aware figure.",
    }
