"""
Significance filter (Phase 5 spec §9) -- the fix for the audit's finding
#1 (docs/orneur/phase-5/CURRENT_MEMORY_ARCHITECTURE.md): today, every
chat turn unconditionally becomes durable LongTermMemory. This module
decides, deterministically and cheaply (no Gateway call -- must stay
fast enough to run on every turn, spec §48), whether an episode is worth
carrying into the MemoryCandidate pipeline at all.

Bounded, regex-based signals -- same "additive, capped" design already
proven in orca/cognitive/risk.py, not a second LLM call in the hot path.
"""
from __future__ import annotations

import re

_EXPLICIT_REMEMBER_RE = re.compile(
    r"\b(remember|don'?t forget|keep in mind|note that|for future reference)\b", re.IGNORECASE,
)
_DECISION_RE = re.compile(
    r"\b(we (decided|agreed|chose)|let'?s go with|final answer|decision:|going with)\b", re.IGNORECASE,
)
_CONFIG_CHANGE_RE = re.compile(
    r"\b(switch(ed)? to|migrat(ed|ing) to|now using|changed (the |our )?(config|setting|model|provider|database))\b",
    re.IGNORECASE,
)
_PREFERENCE_RE = re.compile(
    r"\b(i prefer|i (always|never) want|please always|my preference is)\b", re.IGNORECASE,
)
_FAILURE_RE = re.compile(
    r"\b(that (failed|broke|didn'?t work)|error occurred|root cause|regression|bug found)\b", re.IGNORECASE,
)
_HIGH_CONSEQUENCE_RE = re.compile(
    r"\b(production|deploy(ed|ment)|delete[d]?|drop(ped)? table|security (incident|breach))\b", re.IGNORECASE,
)

_SIGNAL_PATTERNS = [
    ("explicit_remember_request", _EXPLICIT_REMEMBER_RE),
    ("decision_made", _DECISION_RE),
    ("configuration_changed", _CONFIG_CHANGE_RE),
    ("preference_changed", _PREFERENCE_RE),
    ("failure_signal", _FAILURE_RE),
    ("high_consequence_action", _HIGH_CONSEQUENCE_RE),
]


def assess_significance(text: str) -> tuple[bool, list[str]]:
    """Returns (is_significant, matched_signal_names). A blank/very short
    text (casual chatter, greetings) with no matched signal is
    insignificant by default -- absence of a signal is meaningful, not an
    unknown state to round up from (same posture as risk.py's own
    'LOW, not MODERATE-by-default' rule)."""
    matched = [name for name, pattern in _SIGNAL_PATTERNS if pattern.search(text)]
    return bool(matched), matched
