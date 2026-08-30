"""
Intent Compiler -- deterministic, rules-first foundation (Phase 3 spec §7).
Explicitly NOT claimed to be intelligent enough to solve intent routing
permanently: this is pattern-matching over surface language, the same
honesty standard orca/serve/routing.py already applies to its own
heuristics (see docs/orneur/phase-3/CURRENT_COGNITIVE_ORCHESTRATION.md).
The architecture (a single compile_intent() entry point returning an
IntentPlan) allows a future Genesis-powered compiler to replace the body
without changing any caller.
"""
from __future__ import annotations

import re

from orca.cognitive.contracts import (
    ExpectedOutputType,
    IntentCategory,
    IntentPlan,
    PrivacyClass,
)
from orca.cognitive.freshness import assess_freshness

_PATTERNS: dict[IntentCategory, list[re.Pattern]] = {
    IntentCategory.CODING: [re.compile(p, re.IGNORECASE) for p in [
        r"\bwrite (a |some )?code\b", r"\bfunction\b", r"\bdebug\b", r"\bstack trace\b",
        r"\brefactor\b", r"\bcompile error\b", r"\bpython|javascript|typescript|rust|golang\b",
        r"```",
    ]],
    IntentCategory.RESEARCH: [re.compile(p, re.IGNORECASE) for p in [
        r"\bresearch\b", r"\bfind (out |sources |papers )\b", r"\bwho (invented|discovered|wrote)\b",
        r"\baccording to\b", r"\bsources?\b",
    ]],
    IntentCategory.REASONING: [re.compile(p, re.IGNORECASE) for p in [
        r"\bwhy\b", r"\bcompare\b", r"\banalyz(e|is)\b", r"\bstep[- ]by[- ]step\b",
        r"\btrade-?offs?\b", r"\bpros and cons\b", r"\bexplain\b",
    ]],
    IntentCategory.PLANNING: [re.compile(p, re.IGNORECASE) for p in [
        r"\bplan\b", r"\broadmap\b", r"\bschedule\b", r"\bstrategy\b", r"\bnext steps\b",
    ]],
    IntentCategory.TOOL_USE: [re.compile(p, re.IGNORECASE) for p in [
        r"\bsearch (the web|online)\b", r"\brun (this|the) code\b", r"\bexecute\b",
        r"\bcheck (the |a )?(file|directory)\b", r"\bgit (status|log|diff)\b",
    ]],
    IntentCategory.MEMORY_RECALL: [re.compile(p, re.IGNORECASE) for p in [
        r"\bearlier you said\b", r"\blast time\b", r"\bremember when\b", r"\bwe (talked|discussed)\b",
        r"\bwhat did i (say|tell you)\b",
    ]],
    IntentCategory.DOCUMENT_ANALYSIS: [re.compile(p, re.IGNORECASE) for p in [
        r"\bthis document\b", r"\bthe (pdf|file) (i|you) (uploaded|attached)\b",
        r"\bsummarize (this|the) (doc|file|pdf|report)\b",
    ]],
    IntentCategory.AGENTIC: [re.compile(p, re.IGNORECASE) for p in [
        r"\bfigure out\b.*\band\b", r"\bmulti[- ]step\b", r"\borchestrate\b", r"\bgo do\b",
    ]],
    IntentCategory.FACTUAL: [re.compile(p, re.IGNORECASE) for p in [
        r"^\s*(what|who|when|where|how many|how much)('s)?\b", r"\bdefine\b",
    ]],
    IntentCategory.CONVERSATIONAL: [re.compile(p, re.IGNORECASE) for p in [
        r"^\s*(hi|hello|hey|thanks|thank you|good morning|good night)\b",
    ]],
}

_CITATION_INTENTS = {IntentCategory.RESEARCH, IntentCategory.DOCUMENT_ANALYSIS}
_REASONING_INTENTS = {IntentCategory.REASONING, IntentCategory.PLANNING, IntentCategory.CODING, IntentCategory.AGENTIC}
_TOOL_INTENTS = {IntentCategory.TOOL_USE, IntentCategory.CODING, IntentCategory.AGENTIC}
_AGENT_INTENTS = {IntentCategory.AGENTIC}
_RETRIEVAL_INTENTS = {IntentCategory.DOCUMENT_ANALYSIS}
_SEARCH_INTENTS = {IntentCategory.RESEARCH, IntentCategory.TOOL_USE}

def _match_categories(message: str) -> list[IntentCategory]:
    hits = [cat for cat, patterns in _PATTERNS.items() if any(p.search(message) for p in patterns)]
    return hits


def compile_intent(message: str) -> IntentPlan:
    """
    Deterministic given the same input -- no model call. Multi-label:
    every category whose patterns match is a hit; the first match (by
    dict insertion order, most-specific-first) becomes primary_intent,
    the rest become secondary_intents. Falls back to UNKNOWN if nothing
    matches -- never silently guesses CONVERSATIONAL as a fallback,
    since that IS a real classification, not a null case.
    """
    hits = _match_categories(message)
    if not hits:
        primary = IntentCategory.UNKNOWN
        secondary: list[IntentCategory] = []
    else:
        primary, secondary = hits[0], hits[1:]

    all_intents = {primary, *secondary}
    freshness = assess_freshness(message)

    return IntentPlan(
        primary_intent=primary,
        secondary_intents=secondary,
        requires_retrieval=bool(all_intents & _RETRIEVAL_INTENTS),
        requires_search=bool(all_intents & _SEARCH_INTENTS),
        requires_memory=primary == IntentCategory.MEMORY_RECALL or IntentCategory.MEMORY_RECALL in secondary,
        requires_tools=bool(all_intents & _TOOL_INTENTS),
        requires_reasoning=bool(all_intents & _REASONING_INTENTS),
        requires_agents=bool(all_intents & _AGENT_INTENTS),
        citation_requirement=bool(all_intents & _CITATION_INTENTS),
        freshness_requirement=freshness,
        privacy_class=PrivacyClass.STANDARD,
        expected_output_type=ExpectedOutputType.CODE if primary == IntentCategory.CODING else ExpectedOutputType.TEXT,
    )
