"""Lexical, fusion, and synthetic vector ranking.

`synthetic_hash_v1` is a deterministic hashing embedder. It is not a
neural embedding model and must not be reported as one.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter

TOKEN = re.compile(r"\w+", re.UNICODE)
HASH_EMBEDDING_ID = "orneur.rag_x.synthetic_hash_v1"
HASH_DIM = 64


def tokenize(text: str) -> list[str]:
    return [tok.lower() for tok in TOKEN.findall(text)]


def bm25_scores(query: str, documents: list[str], *, k1: float = 1.2, b: float = 0.75) -> list[float]:
    """Okapi BM25. The implementation lives in `orca.docs.sparse` so the research kernel and the authorized index share one scorer."""
    from orca.docs.sparse import bm25_scores as shared_bm25_scores

    return shared_bm25_scores(query, documents, k1=k1, b=b)


def term_count_scores(query: str, documents: list[str]) -> list[float]:
    """Naive overlap count. This is intentionally not BM25."""
    needed = tokenize(query)
    scores = []
    for doc in documents:
        bag = Counter(tokenize(doc))
        scores.append(float(sum(bag[term] for term in needed)))
    return scores


def rrf_fuse(rankings: list[list[int]], *, k: int = 60) -> dict[int, float]:
    """Reciprocal rank fusion. `rankings` are lists of document indexes, best first."""
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, doc_index in enumerate(ranking, start=1):
            fused[doc_index] = fused.get(doc_index, 0.0) + 1.0 / (k + rank)
    return fused


def hash_embed(text: str, *, dim: int = HASH_DIM) -> tuple[float, ...]:
    vector = [0.0] * dim
    tokens = tokenize(text) or [""]
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:2], "big") % dim
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        vector[bucket] += sign
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return tuple(value / norm for value in vector)


def cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return sum(a * b for a, b in zip(left, right))


def token_vectors(text: str, *, dim: int = 16) -> list[tuple[float, ...]]:
    tokens = tokenize(text) or [""]
    return [hash_embed(token, dim=dim) for token in tokens]


def maxsim(query: str, document: str) -> float:
    """Token-level maximum similarity. This is not ColBERT."""
    query_vectors = token_vectors(query)
    doc_vectors = token_vectors(document)
    if not query_vectors or not doc_vectors:
        return 0.0
    total = 0.0
    for qv in query_vectors:
        total += max(cosine(qv, dv) for dv in doc_vectors)
    return total / len(query_vectors)
