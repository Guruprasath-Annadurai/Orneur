"""
Bounded query decomposition for retrieval (Phase 4 spec §8) -- deterministic,
rule-based, no model call. Distinct from orca/cognitive/decomposition.py
(which splits a user OBJECTIVE into sequential sub-objectives for agentic
execution); this splits a QUERY into parallel sub-queries for retrieval
fan-out. Different purpose, different splitting rule -- not reused as-is.
"""
from __future__ import annotations

import re

from orca.truth.planner import MAX_SUBQUERIES

_COMPARE_RE = re.compile(r"\bcompare\b\s+(.+?)\s+(?:and|vs\.?|versus)\s+(.+)", re.IGNORECASE)
_AND_SPLIT_RE = re.compile(r"\s+and\s+", re.IGNORECASE)


def decompose_query(query: str) -> list[str]:
    """
    Returns [query] unchanged (no decomposition) unless a recognized
    comparative/conjunctive pattern is found. Bounded to MAX_SUBQUERIES.
    Never recurses -- one decomposition pass only, matching "no recursive
    unbounded research loop."
    """
    compare_match = _COMPARE_RE.search(query)
    if compare_match:
        a, b = compare_match.group(1).strip(" ?."), compare_match.group(2).strip(" ?.")
        return [f"What is {a}?", f"What is {b}?"][:MAX_SUBQUERIES]

    if _AND_SPLIT_RE.search(query) and query.count("?") <= 1:
        parts = [p.strip(" ?.") for p in _AND_SPLIT_RE.split(query) if p.strip()]
        if len(parts) > 1:
            return parts[:MAX_SUBQUERIES]

    return [query]
