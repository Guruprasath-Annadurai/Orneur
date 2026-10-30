"""
Cross-Encoder Reranker — Ollama-native, no extra ML deps.

Vector search (bi-encoder) gets rough candidates fast but scores query and doc
independently — misses interaction signal. Cross-encoder reranking feeds
(query, doc) pairs together into the LLM and asks for a relevance score.
This is the same trick OpenAI/Cohere rerank APIs use, done here with a local
Ollama call — zero external API.

Also implements Reciprocal Rank Fusion (RRF) to merge multiple retrieval
lists (dense, sparse/BM25, HyDE, multi-query variants) into one ranked list
before the expensive rerank step touches only the top candidates.
"""
from __future__ import annotations

import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass


@dataclass
class ScoredChunk:
    text: str
    filename: str
    chunk_idx: int
    score: float = 0.0
    source: str = ""     # which retriever found it: dense | bm25 | hyde | multiquery
    doc_id: str = ""     # L02-02: the document this chunk belongs to (chunk identity = doc_id + chunk_idx)
    suspect: bool = False  # L02-02e: the passage addresses the judge (score/verdict/role syntax); it was NOT shown to a model and scores 0


def reciprocal_rank_fusion(
    ranked_lists: list[list[dict]],
    k: int = 60,
) -> list[dict]:
    """
    Merge N ranked lists of chunks into one, using RRF:
        score(d) = sum over lists of 1 / (k + rank_in_list)

    Each input list is a list of dicts with at least {'text','filename','chunk_idx'}.
    Dedup key = (doc_id, filename, chunk_idx): two documents that share a filename are different documents.
    """
    fused: dict[tuple, dict] = {}
    for rlist in ranked_lists:
        for rank, item in enumerate(rlist):
            key = (item.get("doc_id", ""), item.get("filename", ""), item.get("chunk_idx", -1))
            rrf_score = 1.0 / (k + rank + 1)
            if key not in fused:
                fused[key] = {**item, "_rrf": 0.0}
            fused[key]["_rrf"] += rrf_score

    merged = list(fused.values())
    merged.sort(key=lambda x: x["_rrf"], reverse=True)
    return merged


_RERANK_PROMPT = """\
{preamble}

Rate how relevant the passage is to the query, on a scale of 0-10.
Only reply with the number, nothing else.

Query: {query}

Passage:
{passage}

Relevance score (0-10):"""


def _ollama_generate(prompt: str, host: str, model: str) -> str:
    try:
        payload = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 5, "temperature": 0.0},
        }).encode()
        req = urllib.request.Request(
            f"{host}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        return data.get("response", "").strip()
    except Exception:
        return ""


def _parse_score(raw: str) -> float:
    """L02-02e: strict. Anything but a bare integer 0-10 is "not scored" and scores 0.0 - it never counts as relevant."""
    from orca.docs.judge import parse_score

    val = parse_score(raw)
    return 0.0 if val is None else val


def cross_encoder_rerank(
    query: str,
    candidates: list[dict],
    ollama_host: str,
    llm_model: str,
    top_k: int = 6,
    max_workers: int = 6,
) -> list[ScoredChunk]:
    """
    Rerank candidate chunks against the query using the LLM as a cross-encoder.
    candidates: list of dicts with 'text', 'filename', 'chunk_idx'.
    Returns top_k ScoredChunk sorted by relevance score descending.

    Scoring calls are independent (query, passage) pairs — fired concurrently
    against Ollama rather than serially, since Ollama can queue/batch requests
    far faster than N sequential round-trips.
    """
    from orca.docs.judge import JUDGE_PREAMBLE, looks_like_judge_injection, untrusted_block

    def _score_one(c: dict) -> ScoredChunk:
        if looks_like_judge_injection(c["text"]):
            # L02-02e: a passage that addresses the scorer never reaches the scorer; it cannot pick its own score.
            return ScoredChunk(text=c["text"], filename=c.get("filename", ""), chunk_idx=c.get("chunk_idx", 0), score=0.0,
                               source=c.get("source", ""), doc_id=c.get("doc_id", ""), suspect=True)
        raw = _ollama_generate(
            _RERANK_PROMPT.format(preamble=JUDGE_PREAMBLE, query=query, passage=untrusted_block(c["text"], 800)),
            host=ollama_host,
            model=llm_model,
        )
        return ScoredChunk(
            text=c["text"],
            filename=c.get("filename", ""),
            chunk_idx=c.get("chunk_idx", 0),
            score=_parse_score(raw),
            source=c.get("source", ""),
            doc_id=c.get("doc_id", ""),
        )

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        scored = list(pool.map(_score_one, candidates))

    scored.sort(key=lambda s: s.score, reverse=True)
    return scored[:top_k]


def fast_lexical_prefilter(
    query: str,
    candidates: list[dict],
    keep: int = 20,
) -> list[dict]:
    """
    Cheap pre-filter before the expensive LLM rerank — cuts candidate count
    using term overlap so the cross-encoder only scores promising chunks.
    """
    if len(candidates) <= keep:
        return candidates

    q_terms = set(re.findall(r"\w+", query.lower()))

    def overlap(c: dict) -> int:
        c_terms = set(re.findall(r"\w+", c["text"].lower()))
        return len(q_terms & c_terms)

    return sorted(candidates, key=overlap, reverse=True)[:keep]
