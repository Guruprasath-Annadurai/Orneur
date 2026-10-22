"""Okapi BM25 shared by the authorized document index and the research kernel.

This is an in-memory scorer over the texts it is given. It is not a durable
posting list. `orca.docs.store.DocStore._bm25_score` is a different,
TF-only fallback and is left unchanged.
"""
from __future__ import annotations

import math
import re
from collections import Counter

TOKEN = re.compile(r"\w+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return [tok.lower() for tok in TOKEN.findall(text)]


def bm25_scores(query: str, documents: list[str], *, k1: float = 1.2, b: float = 0.75) -> list[float]:
    """Okapi BM25. Empty input scores nothing. Empty documents do not divide by zero."""
    tokenized = [tokenize(doc) for doc in documents]
    query_terms = tokenize(query)
    n_docs = len(tokenized)
    if n_docs == 0 or not query_terms:
        return [0.0] * n_docs
    avgdl = sum(len(toks) for toks in tokenized) / n_docs or 1.0
    df: Counter[str] = Counter()
    for toks in tokenized:
        df.update(set(toks))
    scores: list[float] = []
    for toks in tokenized:
        tf = Counter(toks)
        dl = len(toks)
        score = 0.0
        for term in query_terms:
            if term not in tf:
                continue
            idf = math.log(1.0 + (n_docs - df[term] + 0.5) / (df[term] + 0.5))
            denom = tf[term] + k1 * (1.0 - b + b * dl / avgdl)
            score += idf * (tf[term] * (k1 + 1.0)) / denom
        scores.append(score)
    return scores
