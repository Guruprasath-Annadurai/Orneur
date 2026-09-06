# Search Providers (Phase 4)

`orca/truth/search_provider.py` defines `SearchProvider` as a `Protocol`
(`search(query, n=5, *, domain_filter=None) -> list[SearchResultMetadata]`)
so Truth Fabric is never hard-coded around one search backend. A future
paid/API provider is addable by implementing this Protocol — no
`TruthFabric`/`RetrievalPlanner` code changes required; `TruthFabric`
already accepts any `SearchProvider` via its constructor
(`TruthFabric(search_provider=...)`), which is exactly how
`tests/test_truth_fabric_retrieval_modes.py` substitutes a fake provider.

## `DuckDuckGoProvider` — the only provider Phase 4 ships

Wraps the existing, real `orca/tools/web.py::search` — not a
reimplementation of search. `domain_filter` is applied by appending a
`site:<domain>` term to the query string (DuckDuckGo's own search
operator), not by client-side filtering of results. Results whose `url`
is empty (the underlying `search()`'s own failure sentinel — see
`orca/tools/web.py`) are filtered out before reaching `TruthFabric`, so a
search failure surfaces as "zero results," never as a fabricated result
with an empty URL.

## `SearchResultMetadata`

```python
title: str
url: str
snippet: str
domain: str = ""          # hostname, parsed via urllib.parse (never raises on a malformed URL)
published_at: str | None = None
```

## Honest scope: snippets only, no full-page fetch in the live path

`evidence_from_search_result()` (`orca/truth/evidence.py`) builds
`Evidence` directly from a search result's **snippet** — `TruthFabric.
_retrieve()` never calls `orca/truth/fetch.py::fetch_document()` to pull
the full page. The full-page fetch/extract/sanitize pipeline
(`fetch_document`, `extract_text`, `sanitize_extracted_text`,
`evidence_from_fetched_passage`) is real, tested, and its TOCTOU SSRF fix
is genuine (see [SECURITY.md](SECURITY.md)) — but it is not wired into
any retrieval mode's execution path in this phase, including
`RAG_5_RESEARCH`. This is a deliberate, disclosed scope boundary, not an
oversight: full-page fetching adds a materially larger untrusted-content
surface (arbitrary HTML from arbitrary sites, not just a search engine's
own snippet text), and wiring it in without a corresponding review of
how sanitization failures propagate through `assess_evidence()` was
judged out of scope for "first production version." A later phase can
wire `fetch_document()` into `_retrieve()` for `RAG_5_RESEARCH` without
changing `fetch.py`'s own interface.
