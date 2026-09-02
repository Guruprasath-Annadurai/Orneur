"""
Web fetch / extraction boundary (Phase 4 spec §14-15, §43). Separates:
  search result discovery   -- search_provider.py
  document fetching         -- fetch_document() below
  content extraction        -- extract_text() below
  evidence extraction       -- evidence.py

Closes a real, previously-documented security gap: orca/tools/web.py's
own (unreachable, dead) fetch_page() checked the initial URL for SSRF risk
but followed redirects automatically, which is a TOCTOU bypass -- a
malicious server can pass the initial check then redirect to an internal
address. Phase 4 is the first phase to make page-fetching reachable (Deep
Search / RAG_5_RESEARCH), so this gap is closed here rather than carried
forward, per that module's own comment ("must be closed... before this is
ever wired up as a callable tool").
"""
from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from orca.tools.web import HEADERS
from orca.truth.errors import FetchRefusedError

MAX_REDIRECTS = 5
MAX_DOCUMENT_BYTES = 5 * 1024 * 1024   # 5MB -- refuses oversized documents/decompression-bomb-shaped responses
FETCH_TIMEOUT_S = 15.0

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


def _is_ssrf_risk(url: str) -> bool:
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
        return True  # can't resolve/parse -- fail closed
    return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast


@dataclass
class FetchedDocument:
    url: str
    final_url: str
    raw_html: str
    fetched_at_ms: float = 0.0


def fetch_document(url: str, timeout: float = FETCH_TIMEOUT_S) -> FetchedDocument:
    """
    Manually walks redirects (follow_redirects=False), re-checking every
    hop's resolved address against the SSRF check -- the actual fix for
    the TOCTOU gap. Refuses on the first unsafe hop, refuses if the
    redirect chain exceeds MAX_REDIRECTS, and refuses an oversized body
    via a streamed, bounded read rather than trusting Content-Length.
    """
    current_url = url
    with httpx.Client(headers=HEADERS, timeout=timeout, follow_redirects=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            if _is_ssrf_risk(current_url):
                raise FetchRefusedError(internal_detail=f"{current_url} resolves to a private/internal/reserved address")
            with client.stream("GET", current_url) as resp:
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        raise FetchRefusedError(internal_detail="redirect with no Location header")
                    current_url = str(httpx.URL(current_url).join(location))
                    continue

                resp.raise_for_status()
                body = bytearray()
                for chunk in resp.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_DOCUMENT_BYTES:
                        raise FetchRefusedError(internal_detail=f"document exceeds MAX_DOCUMENT_BYTES={MAX_DOCUMENT_BYTES}")
                return FetchedDocument(url=url, final_url=current_url, raw_html=body.decode("utf-8", errors="replace"))

    raise FetchRefusedError(internal_detail=f"exceeded MAX_REDIRECTS={MAX_REDIRECTS}")


def extract_text(raw_html: str, max_chars: int = 8000) -> str:
    """Pure text extraction -- no network, no evidence semantics. Mirrors
    orca/tools/web.py::fetch_page's own cleaning approach (script/style/nav
    stripping), kept identical for behavioral consistency with the one
    provider that already does this for snippets."""
    text = re.sub(r"<script[^>]*>.*?</script>", "", raw_html, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
    text = re.sub(r"<nav[^>]*>.*?</nav>", "", text, flags=re.DOTALL)
    text = re.sub(r"<header[^>]*>.*?</header>", "", text, flags=re.DOTALL)
    text = re.sub(r"<footer[^>]*>.*?</footer>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


@dataclass
class SanitizedDocumentText:
    text: str
    flagged: bool
    matched_patterns: list[str] = field(default_factory=list)


def sanitize_extracted_text(text: str) -> SanitizedDocumentText:
    """
    Retrieved content is untrusted (Phase 4 spec §15). Same pattern-based
    "block, don't guess" posture as orca/tools/search_grounding.py's
    sanitize_fetched_content -- extended here to FULL fetched-page text,
    which that module never covered (it only sanitizes title+snippet).
    Flagged content is excluded from the evidence pipeline entirely by the
    caller (evidence.py), never regex-edited in place.
    """
    matched = [p.pattern for p in _INJECTION_RE if p.search(text)]
    return SanitizedDocumentText(text=text, flagged=bool(matched), matched_patterns=matched)
