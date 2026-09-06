"""
Freshness Requirement -- explicit knowledge-freshness classification
(Phase 3 spec §11), kept as its own bounded module rather than inlined in
intent.py so a future retrieval-planning component (Deep Search, Phase 4+)
has one clear place to call. A question about a mathematical theorem must
not be treated like a stock price or current software release -- this
module is what tells the difference, deterministically.
"""
from __future__ import annotations

import re

from orca.cognitive.contracts import FreshnessLevel, FreshnessRequirement

_REAL_TIME_RE = re.compile(r"\b(right now|breaking|stock price|weather|live score)\b", re.IGNORECASE)
_CURRENT_RE = re.compile(r"\b(today|latest|current(ly)?|this (week|month))\b", re.IGNORECASE)
_RECENT_RE = re.compile(r"\b(this year|recently|these days)\b", re.IGNORECASE)
_LONG_LIVED_RE = re.compile(r"\b(history of|historical|in \d{4}|last (decade|century))\b", re.IGNORECASE)


def assess_freshness(message: str) -> FreshnessRequirement:
    if _REAL_TIME_RE.search(message):
        return FreshnessRequirement(level=FreshnessLevel.REAL_TIME, reasons=["real-time language matched"])
    if _CURRENT_RE.search(message):
        return FreshnessRequirement(level=FreshnessLevel.CURRENT, reasons=["current-state language matched"])
    if _RECENT_RE.search(message):
        return FreshnessRequirement(level=FreshnessLevel.RECENT, reasons=["recency language matched"])
    if _LONG_LIVED_RE.search(message):
        return FreshnessRequirement(level=FreshnessLevel.LONG_LIVED, reasons=["historical language matched"])
    return FreshnessRequirement(level=FreshnessLevel.STATIC, reasons=["no freshness signal found -- treated as timeless (e.g. math, established facts)"])
