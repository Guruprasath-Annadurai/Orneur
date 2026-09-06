"""
Orca Web Tool — search the web without any API key.
Uses DuckDuckGo's HTML interface and direct page fetching.
100% local, no account required.
"""
from __future__ import annotations

import ipaddress
import re
import socket
from typing import NamedTuple
from urllib.parse import quote_plus, urljoin, urlparse

import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

DDG_URL = "https://html.duckduckgo.com/html/?q={query}&kl=us-en"


def _is_ssrf_risk(url: str) -> bool:
    """
    SECURITY: fetch_page() previously accepted any URL with zero
    validation — an SSRF vector (internal services, cloud metadata
    endpoints like 169.254.169.254). Currently unreachable from any
    tool-calling surface (confirmed: nothing in the codebase calls
    fetch_page()), but wiring it up in the future without remembering
    this check would make it live immediately — so the check lives here,
    at the source, rather than depending on a future caller to add it.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return True
    host = parsed.hostname
    if not host:
        return True
    try:
        resolved = socket.gethostbyname(host)
        addr = ipaddress.ip_address(resolved)
    except (socket.gaierror, ValueError):
        return True  # can't resolve/parse it — fail closed, not open
    return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast


class SearchResult(NamedTuple):
    title: str
    url: str
    snippet: str


def search(query: str, n: int = 5) -> list[SearchResult]:
    """Search DuckDuckGo, return top N results."""
    url = DDG_URL.format(query=quote_plus(query))
    try:
        r = httpx.get(url, headers=HEADERS, timeout=10, follow_redirects=True)
        r.raise_for_status()
        return _parse_ddg(r.text, n)
    except Exception as e:
        return [SearchResult(title="Search failed", url="", snippet=str(e))]


def _parse_ddg(html: str, n: int) -> list[SearchResult]:
    results = []
    # Extract result blocks
    blocks = re.findall(
        r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?'
        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
        html, re.DOTALL
    )
    for url, title, snippet in blocks[:n]:
        title = re.sub(r'<[^>]+>', '', title).strip()
        snippet = re.sub(r'<[^>]+>', '', snippet).strip()
        url = url.strip()
        if title and url:
            results.append(SearchResult(title=title, url=url, snippet=snippet))
    return results


def fetch_page(url: str, max_chars: int = 8000) -> str:
    """
    Fetch and clean a webpage, returning readable text.

    HONEST SCOPE: _is_ssrf_risk() checks the URL's resolved address before
    the initial request, but follow_redirects=True below means a malicious
    server could still redirect to an internal address AFTER that check
    passes (a TOCTOU-style bypass) — httpx doesn't cheaply expose per-hop
    redirect inspection. This is a real, known residual gap.

    Phase 4.1 (spec §4): this function's one former caller
    (orca/data/web_ingest.py) has been migrated to the fixed,
    redirect-hop-revalidating orca/truth/fetch.py::fetch_document() — see
    docs/orneur/phase-4/SECURITY.md. This function is now confirmed to
    have zero callers anywhere in the codebase. It is kept only for any
    external/notebook usage that may still import it directly; it must
    not be wired up as a callable tool without first closing this gap the
    same way fetch_document() already does (disable auto-follow-redirects,
    check each hop).
    """
    if _is_ssrf_risk(url):
        return f"Refused to fetch {url}: resolves to a private/internal/reserved address."
    try:
        r = httpx.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
        r.raise_for_status()
        text = r.text

        # Strip scripts, styles, nav
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<nav[^>]*>.*?</nav>', '', text, flags=re.DOTALL)
        text = re.sub(r'<header[^>]*>.*?</header>', '', text, flags=re.DOTALL)
        text = re.sub(r'<footer[^>]*>.*?</footer>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()

        return text[:max_chars]
    except Exception as e:
        return f"Failed to fetch {url}: {e}"


def search_and_fetch(query: str, n: int = 3) -> str:
    """Search + fetch top results. Returns formatted context string."""
    results = search(query, n=n)
    if not results:
        return f"No results for: {query}"

    lines = [f"Search: {query}\n"]
    for i, r in enumerate(results, 1):
        lines.append(f"[{i}] {r.title}")
        lines.append(f"    {r.url}")
        lines.append(f"    {r.snippet}\n")

    return "\n".join(lines)
