"""
SearchProvider abstraction (Phase 4 spec §13). Truth Fabric is NOT
hard-coded around DuckDuckGo -- the existing orca/tools/web.py::search
(real, working, already used by the web_search tool) becomes exactly one
provider implementation behind this interface. A future paid/API provider
is addable by implementing this Protocol, without any Truth Fabric code
changing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class SearchResultMetadata:
    title: str
    url: str
    snippet: str
    domain: str = ""
    published_at: str | None = None


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, n: int = 5, *, domain_filter: str | None = None) -> list[SearchResultMetadata]:
        ...


class DuckDuckGoProvider:
    """Wraps the existing, real orca/tools/web.py::search -- not a
    reimplementation. This is the ONLY provider Phase 4 ships; future
    providers implement the same SearchProvider Protocol."""
    name = "duckduckgo"

    def search(self, query: str, n: int = 5, *, domain_filter: str | None = None) -> list[SearchResultMetadata]:
        from orca.tools.web import search as ddg_search

        q = f"{query} site:{domain_filter}" if domain_filter else query
        results = ddg_search(q, n=n)
        return [
            SearchResultMetadata(title=r.title, url=r.url, snippet=r.snippet, domain=_domain_of(r.url))
            for r in results
            if r.url  # DuckDuckGoProvider.search's own failure sentinel sets url=""
        ]


def _domain_of(url: str) -> str:
    from urllib.parse import urlparse
    try:
        return urlparse(url).hostname or ""
    except Exception:
        return ""
