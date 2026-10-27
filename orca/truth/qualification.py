"""Pre-registered comparison of retrieval arms on a fixed local corpus.

The item list and the negative rule are part of this module. Do not edit
them to make a result look better. Nothing here calls a neural model.
`model_backed` stays false.
"""
from __future__ import annotations

import time
import tracemalloc
from dataclasses import dataclass
from pathlib import Path

from orca.docs.authorized_index import AuthorizedIndex
from orca.rag_x.rank import term_count_scores
from orca.truth.access import SessionAuthority
from orca.truth.indexed_query import fact_conflicts, run_authorized_retrieval

QUALIFICATION_ID = "Q1-canonical-retrieval-v1"
NEGATIVE_IF = (
    "contradiction-first confident-conflict count >= basic retrieval count "
    "OR one-sided sparse miss > 0 OR any citation state is SUPPORTED"
)

# Frozen before the runner is interpreted. Twelve items: seven one-sided,
# four conflicts, one missing. Texts live in DOCUMENTS.
@dataclass(frozen=True)
class QualItem:
    item_id: str
    query: str
    expects_conflict: bool
    expects_token: str | None


DOCUMENTS: tuple[tuple[str, str], ...] = (
    ("widget", "widget status is nominal in bay three"),
    ("bridge", "bridge length is four hundred meters"),
    ("harbor", "harbor depth is charted at twelve meters"),
    ("archive", "archive catalog number is K4"),
    ("pump", "pump pressure is stable at dawn"),
    ("kiln", "kiln temperature is recorded each cycle"),
    ("beacon", "beacon interval is hourly on the east tower"),
    ("lamp-on", "lamp state = on"),
    ("lamp-off", "lamp state = off"),
    ("door-shut", "door state = shut"),
    ("door-open", "door state = open"),
    ("valve-open", "valve position = open"),
    ("valve-closed", "valve position = closed"),
    ("signal-red", "signal color = red"),
    ("signal-green", "signal color = green"),
)

ITEMS: tuple[QualItem, ...] = (
    QualItem("one-sided-widget", "widget status", False, "nominal"),
    QualItem("one-sided-bridge", "bridge length", False, "meters"),
    QualItem("one-sided-harbor", "harbor depth", False, "charted"),
    QualItem("one-sided-archive", "archive catalog", False, "K4"),
    QualItem("one-sided-pump", "pump pressure", False, "stable"),
    QualItem("one-sided-kiln", "kiln temperature", False, "recorded"),
    QualItem("one-sided-beacon", "beacon interval", False, "hourly"),
    QualItem("conflict-lamp", "lamp state", True, None),
    QualItem("conflict-door", "door state", True, None),
    QualItem("conflict-valve", "valve position", True, None),
    QualItem("conflict-signal", "signal color", True, None),
    QualItem("missing-comet", "unmentioned comet", False, None),
)


@dataclass(frozen=True)
class QualificationResult:
    experiment_id: str
    source_documents: int
    evaluation_items: int
    model_backed: bool
    dense_backend: str
    production_neural: bool
    one_sided: int
    sparse_one_sided_hits: int
    sparse_misses: int
    basic_confident_conflicts: int
    contradiction_first_confident_conflicts: int
    citation_supported: int
    citation_partial: int
    abstentions: int
    failures: int
    latency_ms: float
    peak_bytes: int
    negative_rule: str
    hypothesis_supported: bool


def _positive_texts(query: str, rows: list[tuple[str, str]], scores: list[float]) -> list[str]:
    return [text for (_name, text), score in zip(rows, scores) if score > 0]


def run_qualification(root: Path) -> QualificationResult:
    """Score the frozen items once. The runner does not drop or rewrite items."""
    authority = SessionAuthority()
    session = authority.issue("qualification-tenant", "qualification-principal")
    index = AuthorizedIndex(authority, session, root)
    for filename, text in DOCUMENTS:
        index.admit(session, filename, text)
    rows = list(DOCUMENTS)
    texts = [text for _name, text in rows]

    one_sided = 0
    sparse_hits = 0
    sparse_misses = 0
    basic_conflicts = 0
    challenged_conflicts = 0
    citation_supported = 0
    citation_partial = 0
    abstentions = 0
    failures = 0
    dense_backend = "unavailable"
    production_neural = False

    tracemalloc.start()
    started = time.perf_counter()
    try:
        for item in ITEMS:
            try:
                basic_scores = term_count_scores(item.query, texts)
                basic_texts = _positive_texts(item.query, rows, basic_scores)
                if item.expects_conflict and fact_conflicts(basic_texts):
                    basic_conflicts += 1

                answer = run_authorized_retrieval(
                    session, index, item.query, claim=item.query, top_k=4,
                )
                dense_backend = answer.dense_backend
                production_neural = answer.production_neural
                if answer.abstained:
                    abstentions += 1
                if item.expects_conflict and not answer.abstained:
                    challenged_conflicts += 1
                if item.expects_token is not None:
                    one_sided += 1
                    top = answer.hits[0].text if answer.hits else ""
                    if item.expects_token in top and not answer.abstained:
                        sparse_hits += 1
                    else:
                        sparse_misses += 1
                support = answer.claim_support
                if support is not None and support.support_state.value == "SUPPORTED":
                    citation_supported += 1
                if support is not None and support.support_state.value == "PARTIALLY_SUPPORTED":
                    citation_partial += 1
            except Exception:
                failures += 1
    finally:
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    elapsed_ms = (time.perf_counter() - started) * 1000
    hypothesis = (
        challenged_conflicts < basic_conflicts
        and sparse_misses == 0
        and citation_supported == 0
        and failures == 0
    )
    return QualificationResult(
        experiment_id=QUALIFICATION_ID,
        source_documents=len(DOCUMENTS),
        evaluation_items=len(ITEMS),
        model_backed=False,
        dense_backend=dense_backend,
        production_neural=production_neural,
        one_sided=one_sided,
        sparse_one_sided_hits=sparse_hits,
        sparse_misses=sparse_misses,
        basic_confident_conflicts=basic_conflicts,
        contradiction_first_confident_conflicts=challenged_conflicts,
        citation_supported=citation_supported,
        citation_partial=citation_partial,
        abstentions=abstentions,
        failures=failures,
        latency_ms=elapsed_ms,
        peak_bytes=peak,
        negative_rule=NEGATIVE_IF,
        hypothesis_supported=hypothesis,
    )
