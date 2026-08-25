"""
Tests for orca/data/web_ingest.py — the real gap this closes: nothing in
Orca's training pipeline pulled real, grounded source material from the
web (everything was synthetic teacher-model invention). Covers robots.txt
enforcement (real, not decorative) and reuse of fetch_page()'s existing
SSRF protection (see docs/SECURITY_AUDIT.md).
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from orca.data import web_ingest


@pytest.fixture(autouse=True)
def _isolate_corpus_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(web_ingest, "WEB_CORPUS_DIR", tmp_path)
    web_ingest._robots_cache.clear()
    yield
    web_ingest._robots_cache.clear()


def _mock_robots(allowed: bool):
    mock_rp = MagicMock()
    mock_rp.can_fetch.return_value = allowed
    mock_rp.read.return_value = None
    return mock_rp


def test_ingest_fetches_and_saves_allowed_pages(monkeypatch):
    with patch("urllib.robotparser.RobotFileParser", return_value=_mock_robots(True)):
        with patch.object(web_ingest, "fetch_page", return_value="Real page content here."):
            result = web_ingest.ingest_urls(["https://example.com/article"])

    assert result["fetched"] == 1
    assert result["skipped_robots"] == 0
    assert result["failed"] == 0

    lines = [json.loads(l) for l in open(result["output_file"])]
    assert len(lines) == 1
    assert lines[0]["url"] == "https://example.com/article"
    assert lines[0]["text"] == "Real page content here."
    assert lines[0]["char_count"] == len("Real page content here.")


def test_ingest_skips_pages_robots_txt_disallows(monkeypatch):
    with patch("urllib.robotparser.RobotFileParser", return_value=_mock_robots(False)):
        with patch.object(web_ingest, "fetch_page", return_value="Should never be reached.") as mock_fetch:
            result = web_ingest.ingest_urls(["https://example.com/private"])

    assert result["skipped_robots"] == 1
    assert result["fetched"] == 0
    mock_fetch.assert_not_called()


def test_ingest_fails_closed_when_robots_txt_unreachable(monkeypatch):
    """Real design choice: if robots.txt can't be fetched/parsed, treat as
    disallow, not allow — a lightweight tool without an established
    crawler identity shouldn't assume permission by default."""
    broken_rp = MagicMock()
    broken_rp.read.side_effect = Exception("connection refused")

    with patch("urllib.robotparser.RobotFileParser", return_value=broken_rp):
        with patch.object(web_ingest, "fetch_page", return_value="text") as mock_fetch:
            result = web_ingest.ingest_urls(["https://unreachable.example/page"])

    assert result["skipped_robots"] == 1
    mock_fetch.assert_not_called()


def test_ingest_counts_ssrf_refusals_from_fetch_page_as_failed(monkeypatch):
    """fetch_page() already refuses SSRF-risky URLs on its own (returns a
    'Refused to fetch' string, see docs/SECURITY_AUDIT.md) — this must be
    counted as a real failure, not silently written to the corpus."""
    with patch("urllib.robotparser.RobotFileParser", return_value=_mock_robots(True)):
        with patch.object(web_ingest, "fetch_page", return_value="Refused to fetch http://169.254.169.254/: resolves to a private/internal/reserved address."):
            result = web_ingest.ingest_urls(["http://169.254.169.254/"])

    assert result["failed"] == 1
    assert result["fetched"] == 0


def test_ingest_counts_genuine_fetch_failures(monkeypatch):
    with patch("urllib.robotparser.RobotFileParser", return_value=_mock_robots(True)):
        with patch.object(web_ingest, "fetch_page", return_value="Failed to fetch https://example.com: 404 Not Found"):
            result = web_ingest.ingest_urls(["https://example.com/missing"])

    assert result["failed"] == 1


def test_robots_cache_is_reused_per_origin(monkeypatch):
    """Real efficiency property: robots.txt should be fetched once per
    origin, not once per URL, when ingesting multiple pages from the same
    site."""
    mock_rp = _mock_robots(True)
    rp_constructor = MagicMock(return_value=mock_rp)

    with patch("urllib.robotparser.RobotFileParser", rp_constructor):
        with patch.object(web_ingest, "fetch_page", return_value="content"):
            web_ingest.ingest_urls([
                "https://example.com/page1",
                "https://example.com/page2",
                "https://example.com/page3",
            ])

    assert rp_constructor.call_count == 1  # one robots.txt fetch for all 3 same-origin URLs


def test_ingest_handles_multiple_origins_independently(monkeypatch):
    def _rp_factory():
        return _mock_robots(True)

    with patch("urllib.robotparser.RobotFileParser", side_effect=lambda: _rp_factory()):
        with patch.object(web_ingest, "fetch_page", return_value="content"):
            result = web_ingest.ingest_urls([
                "https://siteA.example/page",
                "https://siteB.example/page",
            ])

    assert result["fetched"] == 2
    assert len(web_ingest._robots_cache) == 2
