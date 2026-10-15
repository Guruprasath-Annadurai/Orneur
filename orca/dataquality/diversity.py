"""(5) Diversity measurement from PERMITTED inputs only (the dataset itself): lexical (distinct-n, type-token), structural (skeleton entropy), and an
OPTIONAL semantic measure that runs only through the existing local semantic-engine contract.

Semantic diversity is NOT_EVALUATED unless the caller injects an embedder that is local_only AND semantic_capable AND carries a 64-hex model_sha256
(the contract of orca.eval.genesis_v2.semantic). The lexical FeatureHashEmbedder is never accepted as semantic. This module never loads or downloads
weights; no model directory is configured in this repository.

Metrics are descriptive. This module sets no 'good diversity' threshold of its own beyond caller-supplied minimums, and aggregates nothing into a score.
"""
from __future__ import annotations

import math
from collections import Counter

from orca.dataquality import FAIL, NOT_EVALUATED, PASS
from orca.dataquality._common import body_text, parsed, tokens
from orca.eval.genesis_v2 import similarity as S

OPENING_TOKENS = 8


def _distinct_n(toks_list: list, n: int) -> dict:
    total = 0
    seen: set = set()
    for t in toks_list:
        for i in range(len(t) - n + 1):
            seen.add(tuple(t[i:i + n]))
            total += 1
    return {"total": total, "distinct": len(seen), "ratio": round(len(seen) / total, 4) if total else None}


def _entropy_bits(counter: Counter) -> float:
    n = sum(counter.values())
    return -sum((c / n) * math.log2(c / n) for c in counter.values()) if n else 0.0


def lexical_structural(lines: list, *, min_distinct_2: float | None = None, min_skeleton_norm_entropy: float | None = None) -> dict:
    recs = parsed(lines)
    toks = [tokens(body_text(r.obj)) for r in recs]
    toks = [t for t in toks if t]
    if not toks:
        return {"check": "diversity", "status": NOT_EVALUATED, "reason": "no records with text"}
    flat = [w for t in toks for w in t]
    vocab = len(set(flat))
    d = {n: _distinct_n(toks, n) for n in (1, 2, 3)}
    skel = Counter(" ".join(S.skeleton_tokens(t)) for t in toks)
    h = _entropy_bits(skel)
    hmax = math.log2(len(skel)) if len(skel) > 1 else 0.0
    opening = Counter(" ".join(S.skeleton_tokens(t[:OPENING_TOKENS])) for t in toks)
    ho = _entropy_bits(opening)
    homax = math.log2(len(opening)) if len(opening) > 1 else 0.0
    # per-record type-token ratio (mean) is length-sensitive; reported with the corpus-level one rather than instead of it
    ttr_each = [len(set(t)) / len(t) for t in toks]
    lens = sorted(len(t) for t in toks)
    failing = []
    if min_distinct_2 is not None and (d[2]["ratio"] is None or d[2]["ratio"] < min_distinct_2):
        failing.append("distinct_2_below_minimum")
    if min_skeleton_norm_entropy is not None and (h / hmax if hmax else 0.0) < min_skeleton_norm_entropy:
        failing.append("skeleton_normalized_entropy_below_minimum")
    return {
        "check": "diversity", "status": PASS if not failing else FAIL, "failing_conditions": failing,
        "thresholds": {"min_distinct_2": min_distinct_2, "min_skeleton_normalized_entropy": min_skeleton_norm_entropy,
                       "note": "None = descriptive only; a PASS then means 'computed', not 'diverse enough'"},
        "records": len(toks), "tokens_total": len(flat),
        "lexical": {"vocabulary_size": vocab, "type_token_ratio_corpus": round(vocab / len(flat), 4), "type_token_ratio_mean_per_record": round(sum(ttr_each) / len(ttr_each), 4),
                    "distinct_1": d[1], "distinct_2": d[2], "distinct_3": d[3]},
        "structural": {"distinct_skeletons": len(skel), "skeleton_entropy_bits": round(h, 4),
                       "skeleton_normalized_entropy": round(h / hmax, 4) if hmax else 0.0, "top1_skeleton_share": round(max(skel.values()) / len(toks), 4),
                       "opening_skeleton": {"tokens": OPENING_TOKENS, "distinct": len(opening), "entropy_bits": round(ho, 4),
                                            "normalized_entropy": round(ho / homax, 4) if homax else 0.0, "top1_share": round(max(opening.values()) / len(toks), 4)},
                       "note": "full-body skeletons are near-unique for any prose of different length; the opening-skeleton figures expose shared templates"},
        "length_tokens": {"min": lens[0], "median": lens[len(lens) // 2], "max": lens[-1]},
    }


def semantic(lines: list, embedder=None) -> dict:
    """Mean nearest-neighbour cosine distance among records, via an injected local semantic embedder. NOT_EVALUATED if none is accepted."""
    if embedder is None:
        return {"check": "semantic_diversity", "status": NOT_EVALUATED, "reason": "no local semantic embedder configured (no model directory/hash is authorised in this repository; nothing is downloaded)"}
    ok = bool(getattr(embedder, "local_only", False) and getattr(embedder, "semantic_capable", False)
              and isinstance(getattr(embedder, "model_sha256", None), str) and len(embedder.model_sha256) == 64)
    if not ok:
        return {"check": "semantic_diversity", "status": NOT_EVALUATED,
                "reason": "embedder is not local+semantic-capable+hash-recorded (a lexical proxy is never accepted as semantic evidence)",
                "embedder_model_id": getattr(embedder, "model_id", None)}
    recs = parsed(lines)
    texts = [body_text(r.obj) for r in recs]
    if len(texts) < 2:
        return {"check": "semantic_diversity", "status": NOT_EVALUATED, "reason": "fewer than 2 records"}
    vecs = embedder.embed(texts)
    nn = []
    for i, a in enumerate(vecs):
        best = max(sum(x * y for x, y in zip(a, b)) for j, b in enumerate(vecs) if j != i)
        nn.append(best)
    return {"check": "semantic_diversity", "status": PASS, "records": len(texts), "embedder_model_id": getattr(embedder, "model_id", None),
            "embedder_model_sha256": embedder.model_sha256, "mean_nearest_neighbour_cosine": round(sum(nn) / len(nn), 4),
            "max_nearest_neighbour_cosine": round(max(nn), 4), "note": "descriptive; lower mean NN cosine = more semantically spread"}
