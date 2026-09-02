"""
Truth Fabric evaluation harness (Phase 4 spec §47). Runs TruthFabric
against a small, hand-labeled corpus and computes REAL metrics from
actual retrieval/verification runs -- never fabricated or estimated
numbers. Intentionally a small corpus (see EVALUATION.md for why): this
is a correctness/regression harness for a first production version, not
a claim of statistically significant benchmark results.

Run directly: `.venv/bin/python -m orca.truth.eval_harness`
(requires a local Ollama instance; skips with a clear message if
unreachable, mirroring tests/ollama_test_support.py's policy).
"""
from __future__ import annotations

import asyncio
import json
import math
import time
import uuid
from dataclasses import dataclass, field

from orca.cognitive.contracts import ComplexityLevel, EvidenceLevel, FreshnessLevel
from orca.cognitive.intent import compile_intent
from orca.docs.chunker import Chunk
from orca.docs.store import DocStore
from orca.gateway import wiring as gateway_wiring
from orca.truth.contracts import TruthRequest
from orca.truth.truth_fabric import TruthFabric


@dataclass
class EvalCase:
    case_id: str
    corpus: list[tuple[str, str]]     # (doc_id, text) -- one chunk per doc for this small corpus
    query: str
    relevant_doc_ids: list[str]       # ground truth for Recall@K/MRR/nDCG
    answer_text: str                  # a hand-written candidate answer to verify (not model-generated --
                                       # isolates citation/claim-verification metrics from generation quality)
    expected_supported: bool          # whether answer_text SHOULD be judged supported by this corpus
    expected_contradicted_pair: bool = False  # for the one contradiction-detection case


# Small, hand-labeled corpus -- 6 cases, each with its own tiny document
# set and known-correct relevance judgments. Small on purpose (see
# EVALUATION.md): large-N benchmarking needs a real labeled dataset and a
# GPU budget outside this phase's scope; this harness's job is to prove
# the metrics are computed correctly from real runs, not to produce a
# publishable leaderboard number.
CASES: list[EvalCase] = [
    EvalCase(
        case_id="eiffel_tower",
        corpus=[
            ("d1", "The Eiffel Tower is 330 meters tall and located in Paris, France."),
            ("d2", "The Statue of Liberty is located in New York Harbor."),
            ("d3", "Mount Everest is the tallest mountain above sea level."),
        ],
        query="How tall is the Eiffel Tower and where is it located?",
        relevant_doc_ids=["d1"],
        answer_text="The Eiffel Tower is 330 meters tall and located in Paris, France.",
        expected_supported=True,
    ),
    EvalCase(
        case_id="rate_limit",
        corpus=[
            ("d1", "The API rate limit is 100 requests per minute per API key."),
            ("d2", "Authentication uses a bearer token in the Authorization header."),
            ("d3", "The service has a 99.9% uptime SLA."),
        ],
        query="What is the API rate limit?",
        relevant_doc_ids=["d1"],
        answer_text="The API rate limit is 100 requests per minute per API key.",
        expected_supported=True,
    ),
    EvalCase(
        case_id="unsupported_claim",
        corpus=[
            ("d1", "The company was founded in 2015 and is headquartered in Austin, Texas."),
            ("d2", "The product supports both REST and GraphQL interfaces."),
        ],
        query="When was the company founded?",
        relevant_doc_ids=["d1"],
        answer_text="The company was founded in 2015 and has 500 employees worldwide.",
        expected_supported=False,   # "500 employees" is not in the corpus at all
    ),
    EvalCase(
        case_id="contradiction_pair",
        corpus=[
            ("d1", "As of March 2024, the rate limit is 100 requests per minute."),
            ("d2", "As of the September 2024 update, the rate limit was raised to 500 requests per minute."),
        ],
        query="What is the current rate limit?",
        relevant_doc_ids=["d1", "d2"],
        answer_text="The rate limit is 100 requests per minute.",
        expected_supported=True,   # partially -- d1 supports it, d2 conflicts; verified at claim level, not scored here
        expected_contradicted_pair=True,
    ),
    EvalCase(
        case_id="multi_doc_synthesis",
        corpus=[
            ("d1", "Model A achieves 92% accuracy on the benchmark."),
            ("d2", "Model B achieves 88% accuracy on the same benchmark."),
            ("d3", "The benchmark was introduced in a 2023 paper."),
        ],
        query="Which model performs better on the benchmark, A or B?",
        relevant_doc_ids=["d1", "d2"],
        answer_text="Model A performs better, achieving 92% accuracy versus Model B's 88%.",
        expected_supported=True,
    ),
    EvalCase(
        case_id="no_evidence",
        corpus=[
            ("d1", "The office is located on the fifth floor of the building."),
        ],
        query="What is the capital of a country not mentioned anywhere in this corpus?",
        relevant_doc_ids=[],   # nothing in this tiny corpus is relevant -- tests honest zero-recall handling
        answer_text="The capital is a city not mentioned in the provided documents.",
        expected_supported=False,
    ),
]


def _dcg(relevances: list[int]) -> float:
    return sum(rel / math.log2(i + 2) for i, rel in enumerate(relevances))


def _build_doc_store(case: EvalCase) -> DocStore:
    store = DocStore(session_id=f"eval{uuid.uuid4().hex[:12]}")
    for doc_id, text in case.corpus:
        chunk = Chunk(text=text, doc_id=doc_id, filename=f"{doc_id}.txt", chunk_idx=0, char_start=0, char_end=len(text))
        store.add_chunks([chunk], doc_id=doc_id, filename=f"{doc_id}.txt")
    return store


@dataclass
class CaseResult:
    case_id: str
    recall_at_k: float
    reciprocal_rank: float
    ndcg: float
    citation_coverage_ratio: float | None
    unsupported_claim_rate: float
    contradiction_detected: bool
    retrieval_latency_ms: float
    verification_latency_ms: float
    supported_matches_expected: bool


async def _run_case(fabric: TruthFabric, case: EvalCase) -> CaseResult:
    store = _build_doc_store(case)
    intent = compile_intent(case.query)
    req = TruthRequest(objective=case.query, evidence_requirement=EvidenceLevel.SUPPORTED, freshness_requirement=FreshnessLevel.STATIC)

    t0 = time.monotonic()
    assessed = await fabric.assess_evidence(req, intent, ComplexityLevel.LOW, doc_store=store)
    retrieval_latency_ms = (time.monotonic() - t0) * 1000

    retrieved_doc_ids = [ev.document_id.removesuffix(".txt") for ev in assessed.evidence]
    k = len(retrieved_doc_ids) or 1
    relevant_set = set(case.relevant_doc_ids)

    hits = [1 if doc_id in relevant_set else 0 for doc_id in retrieved_doc_ids]
    recall_at_k = (sum(hits) / len(relevant_set)) if relevant_set else (1.0 if not any(hits) else 0.0)
    reciprocal_rank = next((1.0 / (i + 1) for i, h in enumerate(hits) if h), 0.0) if relevant_set else (1.0 if not hits else 0.0)
    ideal = sorted(hits, reverse=True)
    ndcg = (_dcg(hits) / _dcg(ideal)) if _dcg(ideal) > 0 else (1.0 if not relevant_set else 0.0)

    t1 = time.monotonic()
    final = await fabric.verify_answer(case.answer_text, assessed)
    verification_latency_ms = (time.monotonic() - t1) * 1000

    coverage = final.citation_coverage.get("citation_coverage_ratio")
    total_claims = final.citation_coverage.get("total_claims", 0)
    unsupported = final.citation_coverage.get("unsupported_claims", 0)
    unsupported_rate = (unsupported / total_claims) if total_claims else 0.0
    is_supported = coverage is not None and coverage > 0
    contradiction_detected = bool(final.contradictions)

    return CaseResult(
        case_id=case.case_id, recall_at_k=recall_at_k, reciprocal_rank=reciprocal_rank, ndcg=ndcg,
        citation_coverage_ratio=coverage, unsupported_claim_rate=unsupported_rate,
        contradiction_detected=contradiction_detected, retrieval_latency_ms=retrieval_latency_ms,
        verification_latency_ms=verification_latency_ms, supported_matches_expected=(is_supported == case.expected_supported),
    )


async def run_all() -> dict:
    gateway_wiring.reset_for_tests()
    fabric = TruthFabric()
    results = [await _run_case(fabric, case) for case in CASES]
    gateway_wiring.reset_for_tests()

    n = len(results)
    summary = {
        "cases_run": n,
        "mean_recall_at_k": round(sum(r.recall_at_k for r in results) / n, 3),
        "mrr": round(sum(r.reciprocal_rank for r in results) / n, 3),
        "mean_ndcg": round(sum(r.ndcg for r in results) / n, 3),
        "mean_citation_coverage_ratio": round(
            sum(r.citation_coverage_ratio for r in results if r.citation_coverage_ratio is not None)
            / max(1, sum(1 for r in results if r.citation_coverage_ratio is not None)), 3,
        ),
        "mean_unsupported_claim_rate": round(sum(r.unsupported_claim_rate for r in results) / n, 3),
        "claim_support_precision": round(sum(1 for r in results if r.supported_matches_expected) / n, 3),
        "contradiction_case_detected": next(
            (r.contradiction_detected for r, c in zip(results, CASES) if c.expected_contradicted_pair), None,
        ),
        "mean_retrieval_latency_ms": round(sum(r.retrieval_latency_ms for r in results) / n, 1),
        "mean_verification_latency_ms": round(sum(r.verification_latency_ms for r in results) / n, 1),
        "per_case": [vars(r) for r in results],
    }
    return summary


if __name__ == "__main__":
    from tests.ollama_test_support import ollama_reachable

    if not ollama_reachable():
        print(json.dumps({"error": "No local Ollama instance reachable -- cannot run real metrics."}))
        raise SystemExit(1)

    result = asyncio.run(run_all())
    print(json.dumps(result, indent=2))
