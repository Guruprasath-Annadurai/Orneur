"""
SearchProvider abstraction (Phase 4 spec §13) -- DuckDuckGoProvider wraps
the existing, real orca/tools/web.py::search rather than a reimplementation.
"""
from __future__ import annotations

from orca.truth.search_provider import DuckDuckGoProvider, SearchResultMetadata, _domain_of


def test_duckduckgo_provider_wraps_existing_search(monkeypatch):
    from orca.tools.web import SearchResult

    def _fake_search(query, n=5):
        assert "site:example.com" in query
        return [SearchResult(title="Example Docs", url="https://docs.example.com/x", snippet="snippet text")]

    monkeypatch.setattr("orca.tools.web.search", _fake_search)

    provider = DuckDuckGoProvider()
    results = provider.search("test query", n=5, domain_filter="example.com")
    assert len(results) == 1
    assert isinstance(results[0], SearchResultMetadata)
    assert results[0].domain == "docs.example.com"


def test_duckduckgo_provider_filters_out_failure_sentinel(monkeypatch):
    from orca.tools.web import SearchResult

    def _fake_search(query, n=5):
        return [SearchResult(title="Search failed", url="", snippet="error")]

    monkeypatch.setattr("orca.tools.web.search", _fake_search)

    provider = DuckDuckGoProvider()
    results = provider.search("test query")
    assert results == []


def test_domain_of_extracts_hostname():
    assert _domain_of("https://docs.example.com/path?q=1") == "docs.example.com"


def test_domain_of_handles_malformed_url():
    assert _domain_of("not a url") == ""
