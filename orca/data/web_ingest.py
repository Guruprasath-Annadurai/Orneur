"""
Web ingestion — real gap this closes: Orca's training data pipeline
(orca/data/collector.py) generates SFT examples entirely via synthetic
teacher-model invention (a teacher model imagines both the question and
the answer). Nothing pulls real, grounded source material from the web to
either (a) feed the RAG document store for factual grounding, or (b) serve
as real source material a teacher model can be asked to generate Q&A
pairs FROM — a genuinely more grounded distillation approach than pure
invention.

Respects robots.txt (real, checked before every fetch, not decorative).

Phase 4.1 (spec §4): migrated off orca/tools/web.py's fetch_page(), whose
SSRF check only validated the initial URL and then followed redirects
automatically (a TOCTOU bypass — see docs/orneur/phase-4/SECURITY.md).
Uses orca/truth/fetch.py's fetch_document()/extract_text() instead, which
re-validates every redirect hop. Single-machine, sequential, no JS
rendering (static HTML only via httpx) — honestly scoped as a lightweight
corpus builder, not a production-grade distributed crawler.
"""
from __future__ import annotations

import json
import time
import urllib.robotparser
from dataclasses import dataclass, field
from urllib.parse import urlparse

from orca.config import ORCA_HOME
from orca.truth.errors import FetchRefusedError
from orca.truth.fetch import extract_text, fetch_document

WEB_CORPUS_DIR = ORCA_HOME / "training" / "web_corpus"
WEB_CORPUS_DIR.mkdir(parents=True, exist_ok=True)

_robots_cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}


def _robots_allows(url: str, user_agent: str = "*") -> bool:
    """
    Checks robots.txt before fetching a URL — real, not decorative. Fails
    CLOSED (disallow) if robots.txt can't be fetched or parsed, since for
    a lightweight ingestion tool without an established, well-known
    crawler identity, an unreachable robots.txt more often signals "this
    site isn't set up to be crawled" than "anything goes."
    """
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    if origin not in _robots_cache:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(f"{origin}/robots.txt")
        try:
            rp.read()
            _robots_cache[origin] = rp
        except Exception:
            _robots_cache[origin] = None

    rp = _robots_cache.get(origin)
    if rp is None:
        return False
    return rp.can_fetch(user_agent, url)


@dataclass
class IngestedPage:
    url: str
    text: str
    fetched_at: float = field(default_factory=time.time)
    char_count: int = 0

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "text": self.text,
            "fetched_at": self.fetched_at,
            "char_count": self.char_count,
        }


def ingest_urls(urls: list[str], max_chars_per_page: int = 8000, on_log=None) -> dict:
    """
    Fetches and cleans each URL — skipping anything robots.txt disallows,
    and anything fetch_document() itself refuses (SSRF-risky targets,
    redirect-hop violations, oversized documents, fetch failures) — and
    appends the cleaned text to a dated JSONL corpus file under
    WEB_CORPUS_DIR.

    Returns a summary dict: counts (fetched/skipped_robots/failed) and the
    output file path. Each real fetch produces a real entry an operator or
    a later distillation step can read — nothing here fabricates content.
    """
    log = on_log or (lambda msg: None)
    output_path = WEB_CORPUS_DIR / f"web_corpus_{time.strftime('%Y%m%d')}.jsonl"

    fetched = 0
    skipped_robots = 0
    failed = 0

    with open(output_path, "a") as out_f:
        for i, url in enumerate(urls):
            if not _robots_allows(url):
                skipped_robots += 1
                log(f"[web-ingest] [{i+1}/{len(urls)}] robots.txt disallows, skipped: {url}")
                continue

            try:
                doc = fetch_document(url)
            except FetchRefusedError as e:
                failed += 1
                log(f"[web-ingest] [{i+1}/{len(urls)}] FAILED: {e.message} ({e.internal_detail})")
                continue
            except Exception as e:
                # A genuine HTTP/network failure (404, connection error,
                # etc.) from httpx -- not an SSRF refusal, but still a
                # real failure to count, never silently skipped or
                # written to the corpus as if it succeeded.
                failed += 1
                log(f"[web-ingest] [{i+1}/{len(urls)}] FAILED: {e}")
                continue
            text = extract_text(doc.raw_html, max_chars=max_chars_per_page)

            page = IngestedPage(url=url, text=text, char_count=len(text))
            out_f.write(json.dumps(page.to_dict()) + "\n")
            fetched += 1
            log(f"[web-ingest] [{i+1}/{len(urls)}] fetched {len(text)} chars: {url}")

    result = {
        "requested": len(urls),
        "fetched": fetched,
        "skipped_robots": skipped_robots,
        "failed": failed,
        "output_file": str(output_path),
    }
    log(f"[web-ingest] done — {fetched} fetched, {skipped_robots} robots-blocked, {failed} failed")
    return result


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("urls", nargs="+", help="One or more URLs to ingest")
    parser.add_argument("--max-chars", type=int, default=8000)
    args = parser.parse_args()

    def log(msg):
        print(msg, flush=True)

    result = ingest_urls(args.urls, max_chars_per_page=args.max_chars, on_log=log)
    print(f"\nWeb ingest — {result['fetched']} fetched, {result['skipped_robots']} robots-blocked, {result['failed']} failed")
    print(f"Output: {result['output_file']}")


if __name__ == "__main__":
    main()
