"""
Tests for orca/tools/web.py's _is_ssrf_risk() — added after an OWASP-style
review found fetch_page() accepted any URL with zero validation. Currently
unreachable from any tool-calling surface (confirmed dead code), but a
future wiring of this function without this check would make SSRF to
internal services / cloud metadata endpoints live immediately.
"""
from __future__ import annotations

import socket
from unittest.mock import patch

from orca.tools.web import _is_ssrf_risk, fetch_page


def _mock_resolve(mapping: dict[str, str]):
    def _fake_gethostbyname(host):
        if host in mapping:
            return mapping[host]
        raise socket.gaierror(f"no mock entry for {host}")
    return _fake_gethostbyname


def test_blocks_non_http_schemes():
    assert _is_ssrf_risk("file:///etc/passwd") is True
    assert _is_ssrf_risk("ftp://example.com") is True


def test_blocks_loopback_address():
    with patch("socket.gethostbyname", _mock_resolve({"localhost": "127.0.0.1"})):
        assert _is_ssrf_risk("http://localhost/admin") is True


def test_blocks_cloud_metadata_endpoint():
    with patch("socket.gethostbyname", _mock_resolve({"169.254.169.254": "169.254.169.254"})):
        assert _is_ssrf_risk("http://169.254.169.254/latest/meta-data/") is True


def test_blocks_private_network_ranges():
    with patch("socket.gethostbyname", _mock_resolve({"internal.corp": "10.0.0.5"})):
        assert _is_ssrf_risk("http://internal.corp/") is True
    with patch("socket.gethostbyname", _mock_resolve({"internal2.corp": "192.168.1.1"})):
        assert _is_ssrf_risk("http://internal2.corp/") is True


def test_allows_genuine_public_address():
    with patch("socket.gethostbyname", _mock_resolve({"example.com": "93.184.216.34"})):
        assert _is_ssrf_risk("https://example.com/page") is False


def test_fails_closed_when_hostname_does_not_resolve():
    with patch("socket.gethostbyname", _mock_resolve({})):
        assert _is_ssrf_risk("http://this-does-not-resolve.invalid/") is True


def test_fetch_page_refuses_ssrf_risk_before_making_a_request():
    with patch("orca.tools.web._is_ssrf_risk", return_value=True):
        result = fetch_page("http://169.254.169.254/")
    assert "Refused to fetch" in result


def test_fetch_page_proceeds_normally_when_not_a_risk():
    with patch("orca.tools.web._is_ssrf_risk", return_value=False):
        with patch("httpx.get") as mock_get:
            mock_get.return_value.raise_for_status.return_value = None
            mock_get.return_value.text = "<html><body>hello</body></html>"
            result = fetch_page("https://example.com")
    assert "hello" in result
