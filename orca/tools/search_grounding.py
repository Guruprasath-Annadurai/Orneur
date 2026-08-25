"""
Search grounding — extends Orca's existing web_search tool (orca/tools/web.py,
DuckDuckGo-based, no API key required) with the two things it lacked:

  1. Enforced source citations. Web results are numbered as [S1], [S2], ...
     and the model is instructed to cite them — the same discipline
     orca/docs/citation_check.py already applies to uploaded documents
     ([D#] markers), extended to live web sources.

  2. Sanitization of fetched content. A web search result is untrusted,
     attacker-reachable input — indirect prompt injection via scraped page
     text/snippets is a real, known risk for any search-grounded AI product,
     not a theoretical one. This module flags injection-shaped content and
     excludes it from the model's context entirely rather than trying to
     regex-edit it (editing arbitrary web prose in place is unreliable and
     can silently mangle legitimate content) — matching the "block, don't
     guess" posture orca/serve/moderation.py already takes for chat input.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from orca.tools.web import search

_INJECTION_PATTERNS = [
    r"\bignore (all )?(previous|prior|the above)\b.{0,15}\binstructions\b",
    r"\byou are now\b.{0,30}\b(DAN|an AI|acting as)\b",
    r"\bsystem\s*:\s*\S",
    r"\bnew instructions?\b.{0,20}\bfrom (the )?(developer|system|admin)\b",
    r"\bdisregard (all )?(previous|prior|safety)\b",
    r"\[system\]|\[/system\]|<\|system\|>",
    r"\bthis (page|document|site) (overrides|supersedes) (your|all)\b.{0,20}\b(instructions|rules)\b",
    r"\bact as\b.{0,20}\bwith no (restrictions|filters)\b",
]

_INJECTION_RE = [re.compile(p, re.IGNORECASE) for p in _INJECTION_PATTERNS]


@dataclass
class SanitizedContent:
    text: str
    flagged: bool
    matched_patterns: list[str] = field(default_factory=list)


def sanitize_fetched_content(text: str) -> SanitizedContent:
    """
    Scans fetched web content for embedded instruction-injection attempts
    before it can reach the model's context.
    """
    matched = [p.pattern for p in _INJECTION_RE if p.search(text)]
    return SanitizedContent(text=text, flagged=bool(matched), matched_patterns=matched)


@dataclass
class GroundedSource:
    index: int  # 1-based, matches the [S#] marker used in the context block
    title: str
    url: str
    snippet: str
    flagged: bool = False
    flag_reason: str = ""


def search_and_ground(query: str, n: int = 5) -> tuple[str, list[GroundedSource]]:
    """
    Search + sanitize + format as a numbered [S#] source block for the model
    to cite from. Returns (context_string, sources) — context_string is what
    gets fed to the model (flagged sources are excluded from it entirely),
    sources is the full list including flagged ones, for audit/UI visibility.
    """
    results = search(query, n=n)
    sources: list[GroundedSource] = []

    if not results:
        return f"No search results for: {query}", sources

    context_lines = [f"Search: {query}\n"]
    for idx, r in enumerate(results, start=1):
        check = sanitize_fetched_content(f"{r.title} {r.snippet}")
        source = GroundedSource(
            index=idx, title=r.title, url=r.url, snippet=r.snippet,
            flagged=check.flagged,
            flag_reason=f"matched injection pattern: {check.matched_patterns[0]}" if check.flagged else "",
        )
        sources.append(source)

        if check.flagged:
            context_lines.append(f"[S{idx}] SOURCE EXCLUDED — flagged content, not shown to model ({r.url})\n")
            continue

        context_lines.append(f"[S{idx}] {r.title}")
        context_lines.append(f"    {r.url}")
        context_lines.append(f"    {r.snippet}\n")

    context_lines.append(
        "Cite the sources you actually used with their [S#] marker. If you make "
        "a claim that isn't supported by any [S#] source above, say plainly that "
        "it's from general knowledge, not from this search."
    )
    return "\n".join(context_lines), sources
